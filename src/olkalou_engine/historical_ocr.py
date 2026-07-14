from __future__ import annotations

import csv
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Protocol

from .config import Settings
from .ocr.handwriting import extract_form35a_numeric_cells, reconcile_form35a_fields

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
FORM_35A = "35A"
FORM_35B = "35B"
OTHER = "OTHER"
OCR_PIPELINE_VERSION = "2026.07.14-layout-v2"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _safe_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = re.sub(r"[^0-9]", "", str(value))
    return int(text) if text else None


@dataclass(frozen=True)
class OCRText:
    text: str
    confidence: float
    engine: str


class PageTextEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, page_image: Path) -> OCRText: ...


class TesseractEngine:
    """Local OCR fallback. It is a pre-fill engine, never a publication authority."""

    name = "tesseract"

    def __init__(self) -> None:
        self._module = None
        try:
            import pytesseract

            self._module = pytesseract
        except ImportError:
            self._module = None

    def available(self) -> bool:
        if self._module is None:
            return False
        try:
            self._module.get_tesseract_version()
        except Exception:
            return False
        return True

    def read(self, page_image: Path) -> OCRText:
        if not self.available():
            raise RuntimeError(
                "Tesseract OCR is unavailable. Install Tesseract and pip install -e '.[historical-ocr]'."
            )
        from PIL import Image
        from pytesseract import Output

        image = Image.open(page_image)
        data = self._module.image_to_data(image, output_type=Output.DICT, config="--psm 6")
        words: list[str] = []
        confidences: list[float] = []
        line_parts: dict[tuple[int, int, int], list[str]] = {}
        for index, text in enumerate(data.get("text", [])):
            cleaned = (text or "").strip()
            if not cleaned:
                continue
            key = (
                int(data.get("block_num", [0])[index]),
                int(data.get("par_num", [0])[index]),
                int(data.get("line_num", [0])[index]),
            )
            line_parts.setdefault(key, []).append(cleaned)
            words.append(cleaned)
            try:
                confidence = float(data.get("conf", ["-1"])[index])
            except (TypeError, ValueError):
                confidence = -1
            if confidence >= 0:
                confidences.append(confidence / 100.0)
        lines = [" ".join(parts) for _, parts in sorted(line_parts.items())]
        return OCRText(
            text="\n".join(lines) if lines else " ".join(words),
            confidence=mean(confidences) if confidences else 0.0,
            engine=self.name,
        )


class GoogleVisionPageEngine:
    name = "gcv"

    def __init__(self, credentials_json: Path | None = None) -> None:
        if credentials_json:
            import os

            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(credentials_json))
        try:
            from google.cloud import vision
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install cloud OCR dependencies: pip install -e '.[ocr]'") from exc
        self.vision = vision
        self.client = vision.ImageAnnotatorClient()

    def available(self) -> bool:
        return True

    def read(self, page_image: Path) -> OCRText:
        response = self.client.document_text_detection(
            image=self.vision.Image(content=page_image.read_bytes())
        )
        if response.error.message:
            raise RuntimeError(response.error.message)
        annotation = response.full_text_annotation
        confidences: list[float] = []
        for page in annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        confidences.extend(
                            symbol.confidence for symbol in word.symbols if symbol.confidence
                        )
        return OCRText(
            text=(annotation.text or "").strip(),
            confidence=mean(confidences) if confidences else 0.0,
            engine=self.name,
        )


class TextractPageEngine:
    name = "textract"

    def __init__(self, region: str) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install cloud OCR dependencies: pip install -e '.[ocr]'") from exc
        self.client = boto3.client("textract", region_name=region)

    def available(self) -> bool:
        return True

    def read(self, page_image: Path) -> OCRText:
        response = self.client.detect_document_text(Document={"Bytes": page_image.read_bytes()})
        lines = [block for block in response.get("Blocks", []) if block.get("BlockType") == "LINE"]
        return OCRText(
            text="\n".join(str(line.get("Text", "")).strip() for line in lines).strip(),
            confidence=mean(float(line.get("Confidence", 0.0)) / 100.0 for line in lines)
            if lines
            else 0.0,
            engine=self.name,
        )


def _page_count(path: Path) -> int:
    if path.suffix.lower() != ".pdf":
        return 1
    try:
        import pypdfium2 as pdfium

        return len(pdfium.PdfDocument(str(path)))
    except Exception:
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return len(pdf.pages)
        except Exception:
            return 1


def _embedded_text(path: Path, page_no: int) -> str:
    if path.suffix.lower() != ".pdf":
        return ""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            if page_no < 1 or page_no > len(pdf.pages):
                return ""
            return (pdf.pages[page_no - 1].extract_text(x_tolerance=2, y_tolerance=3) or "").strip()
    except Exception:
        return ""


def _render_page(path: Path, page_no: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".pdf":
        target = output_dir / f"page-{page_no}{path.suffix.lower()}"
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return target
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PDF OCR requires pypdfium2 from the pdf or ocr extra") from exc
    pdf = pdfium.PdfDocument(str(path))
    if page_no < 1 or page_no > len(pdf):
        raise ValueError(f"page {page_no} does not exist in {path}")
    bitmap = pdf[page_no - 1].render(scale=4.0)
    target = output_dir / f"page-{page_no}.png"
    bitmap.to_pil().save(target)
    return target


def _document_roots(bundle: Any, extra_paths: Iterable[Path] | None = None) -> list[Path]:
    roots = [
        bundle.election_dir / "documents",
        bundle.election_dir / "forms",
        bundle.root / "data" / "uploads" / bundle.election_id,
        bundle.root / "data" / "public" / "elections" / bundle.election_id / "forms",
    ]
    roots.extend(extra_paths or [])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = root if root.is_absolute() else bundle.root / root
        marker = str(resolved.resolve())
        if marker not in seen:
            seen.add(marker)
            unique.append(resolved)
    return unique


def inventory_documents(bundle: Any, extra_paths: Iterable[Path] | None = None) -> dict[str, Any]:
    by_sha: dict[str, dict[str, Any]] = {}
    scanned_roots: list[str] = []
    for root in _document_roots(bundle, extra_paths):
        scanned_roots.append(_relative(root, bundle.root))
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        generated_uploads = (
            bundle.root
            / "data"
            / "public"
            / "elections"
            / bundle.election_id
            / "forms"
            / "uploaded"
        ).resolve()
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                path.resolve().relative_to(generated_uploads)
                # This is the immutable mirror produced by this inventory pass,
                # not an independent uploaded source.
                continue
            except ValueError:
                pass
            digest = _sha256(path)
            record = by_sha.get(digest)
            alias = _relative(path, bundle.root)
            if record:
                if alias not in record["aliases"]:
                    record["aliases"].append(alias)
                continue
            public_relative = (
                Path("elections")
                / bundle.election_id
                / "forms"
                / "uploaded"
                / f"{digest[:16]}{path.suffix.lower()}"
            )
            public_path = bundle.root / "data" / "public" / public_relative
            public_path.parent.mkdir(parents=True, exist_ok=True)
            if not public_path.exists():
                shutil.copy2(path, public_path)
            by_sha[digest] = {
                "sha256": digest,
                "path": alias,
                "aliases": [alias],
                "filename": path.name,
                "extension": path.suffix.lower(),
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "size_bytes": path.stat().st_size,
                "pages": _page_count(path),
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "public_path": _relative(public_path, bundle.root),
                "public_url": f"../data/public/{public_relative.as_posix()}",
            }
    documents = sorted(by_sha.values(), key=lambda item: item["path"])
    inventory = {
        "schema": "kenya.election.ocr-inventory.v1",
        "election_id": bundle.election_id,
        "generated_at": utc_now_iso(),
        "roots": scanned_roots,
        "documents_total": len(documents),
        "pages_total": sum(int(item["pages"]) for item in documents),
        "duplicates_collapsed": sum(max(0, len(item["aliases"]) - 1) for item in documents),
        "documents": documents,
    }
    output = bundle.election_dir / "ocr" / "document_inventory.json"
    _write_json(output, inventory)
    return inventory


def _extract_number_near_labels(text: str, labels: Iterable[str]) -> tuple[int | None, str | None]:
    lines = [re.sub(r"\s+", " ", raw_line).strip() for raw_line in text.splitlines()]
    # Labels are ordered strongest-first. Search each label across all lines before
    # falling back to a weaker token, otherwise a shared surname can bind the
    # wrong candidate row.
    for label in labels:
        clean_label = re.sub(r"\s+", " ", label).strip().upper()
        if not clean_label:
            continue
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(clean_label)}(?![A-Z0-9])")
        for line in lines:
            upper = line.upper()
            if not pattern.search(upper):
                continue
            values = re.findall(r"(?<![A-Z0-9])([0-9][0-9, ]{0,8})(?![A-Z0-9])", line)
            numbers = [_safe_int(value) for value in values]
            numbers = [number for number in numbers if number is not None]
            if numbers:
                return numbers[-1], line
    return None, None


def classify_form(text: str, filename: str) -> str:
    marker = f"{filename}\n{text[:5000]}".upper()
    if re.search(r"FORM\s*35\s*B|FORM\s*35B|CONSTITUENCY\s+TALLY|DECLARATION\s+OF\s+RESULT", marker):
        return FORM_35B
    if re.search(r"FORM\s*35\s*A|FORM\s*35A|POLLING\s+STATION.*RESULT", marker, re.S):
        return FORM_35A
    compact_name = filename.upper().replace("_", " ").replace("-", " ")
    if "35B" in compact_name:
        return FORM_35B
    if "35A" in compact_name:
        return FORM_35A
    return OTHER


def match_stream(bundle: Any, text: str, filename: str) -> tuple[dict[str, Any] | None, str | None]:
    marker = f"{filename}\n{text[:10000]}"
    upper = marker.upper()
    stream_no_match = re.findall(r"(?:STREAM|STRM)\s*(?:NO\.?\s*)?0?([0-9]{1,2})", upper)
    if not stream_no_match:
        # The real printed Form 35A header reads "<STATION NAME> POLLING
        # STATION X of Y" -- e.g. "OGONDICHO PRIMARY SCHOOL POLLING STATION
        # 2 of 2" -- confirmed directly against a real scanned Banissa form.
        # "Stream N" does not appear anywhere on the form itself, so treat
        # this as the primary pattern to expect, not a rare fallback.
        stream_no_match = re.findall(r"POLLING\s*STATION\s*([0-9]{1,2})\s*OF\s*[0-9]{1,2}", upper)
    stream_no = int(stream_no_match[-1]) if stream_no_match else None

    code_hits: list[dict[str, Any]] = []
    digit_tokens = set(re.findall(r"(?<![0-9])([0-9]{4,15})(?![0-9])", marker))
    for row in bundle.streams:
        code = str(row.get("polling_station_code") or "").strip()
        if code and (code in digit_tokens or any(token.endswith(code) for token in digit_tokens)):
            code_hits.append(row)
    if stream_no is not None:
        narrowed = [row for row in code_hits if int(row.get("stream_no", 1)) == stream_no]
        if len(narrowed) == 1:
            return narrowed[0], "POLLING_CODE_AND_STREAM"
    if len(code_hits) == 1:
        return code_hits[0], "POLLING_CODE"

    norm_marker = _norm(marker)
    name_hits = [
        row
        for row in bundle.streams
        if len(_norm(str(row.get("station_name", "")))) >= 5
        and _norm(str(row.get("station_name", ""))) in norm_marker
    ]
    if stream_no is not None:
        narrowed = [row for row in name_hits if int(row.get("stream_no", 1)) == stream_no]
        if len(narrowed) == 1:
            return narrowed[0], "STATION_NAME_AND_STREAM"
    if len(name_hits) == 1:
        return name_hits[0], "STATION_NAME"
    return None, None


def _candidate_labels(candidate: dict[str, Any]) -> list[str]:
    name = str(candidate.get("name") or "").strip()
    abbr = str(candidate.get("abbr") or "").strip()
    name_parts = [part for part in re.split(r"\s+", name) if len(part) >= 4]
    # Full legal name is the strongest key, followed by party abbreviation and
    # then the least ambiguous given-name tokens. The surname is deliberately
    # last because Kenyan candidate lists can contain relatives/shared surnames.
    labels = [name, abbr]
    if len(name_parts) >= 2:
        labels.extend(name_parts[:-1])
    if name_parts:
        labels.append(name_parts[-1])
    return [label for label in labels if label]


def parse_form35a(text: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {}
    evidence: dict[str, str | None] = {}
    for candidate in candidates:
        candidate_id = str(candidate["id"])
        value, line = _extract_number_near_labels(text, _candidate_labels(candidate))
        fields[f"candidate_{candidate_id}"] = {
            "value": value,
            "confidence": 0.78 if value is not None else 0.0,
        }
        evidence[f"candidate_{candidate_id}"] = line

    control_labels = {
        "registered": ["REGISTERED VOTERS", "NUMBER OF REGISTERED", "REGISTERED ELECTORS"],
        # "REJECTED BALLOTS" never matched the real form -- it prints "Total
        # Number of Rejected Ballot Papers" (no trailing S on BALLOT, plus
        # "PAPERS"), confirmed directly against a real scanned form. This
        # single mismatch meant `rejected` could never be extracted from any
        # real Banissa form regardless of OCR quality -- a pure label bug,
        # not an accuracy problem.
        "rejected": ["REJECTED BALLOT PAPERS", "REJECTED BALLOTS", "REJECTED VOTES", "TOTAL REJECTED"],
        "total_valid": ["TOTAL NUMBER OF VALID VOTES", "TOTAL VALID VOTES", "VALID VOTES CAST", "TOTAL NUMBER OF VALID"],
        "total_cast": ["TOTAL VOTES CAST", "TOTAL BALLOTS CAST", "TOTAL NUMBER OF VOTES CAST"],
        # Present on the real form's "Polling Station Counts" box but not
        # previously extracted at all -- harmless to capture even though
        # nothing downstream currently reads them; free evidence for a human
        # reviewer glancing at the form.
        "rejection_objections": ["REJECTION OBJECTED TO BALLOT PAPERS", "OBJECTED TO BALLOT PAPERS"],
        "disputed_votes": ["NUMBER OF DISPUTED VOTES", "TOTAL NUMBER OF DISPUTED"],
    }
    for field, labels in control_labels.items():
        value, line = _extract_number_near_labels(text, labels)
        fields[field] = {"value": value, "confidence": 0.82 if value is not None else 0.0}
        evidence[field] = line

    # This Form 35A layout has no explicit "total votes cast" line at all
    # (confirmed against a real form: Registered / Rejected / Rejection-
    # objections / Disputed / Valid are the only five counted rows) -- derive
    # it rather than leave it permanently blank whenever both inputs are
    # available. Lower confidence than either operand since it inherits
    # whatever error either one carries, and openly says so in evidence.
    if fields["total_cast"]["value"] is None:
        valid = fields["total_valid"]["value"]
        rejected = fields["rejected"]["value"]
        if valid is not None and rejected is not None:
            fields["total_cast"] = {
                "value": valid + rejected,
                "confidence": min(fields["total_valid"]["confidence"], fields["rejected"]["confidence"]),
            }
            evidence["total_cast"] = f"derived: total_valid ({valid}) + rejected ({rejected})"

    return {"fields": fields, "evidence": evidence}


def parse_form35b(text: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_totals: dict[str, int | None] = {}
    evidence: dict[str, str | None] = {}
    for candidate in candidates:
        candidate_id = str(candidate["id"])
        value, line = _extract_number_near_labels(text, _candidate_labels(candidate))
        candidate_totals[candidate_id] = value
        evidence[candidate_id] = line
    valid_votes, valid_line = _extract_number_near_labels(
        text, ["TOTAL VALID VOTES", "VALID VOTES CAST", "TOTAL NUMBER OF VALID"]
    )
    rejected_votes, rejected_line = _extract_number_near_labels(
        text, ["REJECTED BALLOTS", "REJECTED VOTES", "TOTAL REJECTED"]
    )
    total_cast, cast_line = _extract_number_near_labels(
        text, ["TOTAL VOTES CAST", "TOTAL BALLOTS CAST", "TOTAL NUMBER OF VOTES CAST"]
    )
    evidence.update({"valid_votes": valid_line, "rejected_votes": rejected_line, "total_cast": cast_line})
    return {
        "candidate_totals": candidate_totals,
        "valid_votes": valid_votes,
        "rejected_votes": rejected_votes,
        "total_cast": total_cast,
        "evidence": evidence,
    }


def _checks_for_extraction(
    parsed: dict[str, Any],
    reference: dict[str, Any] | None,
    candidate_ids: list[str],
    *,
    candidate_list_complete: bool = True,
) -> dict[str, str]:
    fields = parsed.get("fields", {})
    votes = [fields.get(f"candidate_{candidate_id}", {}).get("value") for candidate_id in candidate_ids]
    rejected = fields.get("rejected", {}).get("value")
    total_valid = fields.get("total_valid", {}).get("value")
    total_cast = fields.get("total_cast", {}).get("value")
    registered_form = fields.get("registered", {}).get("value")
    checks = {"V01": "NOT_RUN", "V02": "NOT_RUN", "V03": "NOT_RUN", "V07": "NOT_RUN"}
    if candidate_list_complete and all(value is not None for value in votes) and total_valid is not None:
        checks["V01"] = "PASS" if sum(int(value) for value in votes) == int(total_valid) else "FAIL"
    if total_valid is not None and rejected is not None and total_cast is not None:
        checks["V02"] = "PASS" if int(total_valid) + int(rejected) == int(total_cast) else "FAIL"
    reference_registered = reference.get("registered") if reference is not None else None
    if reference_registered is not None and total_cast is not None:
        checks["V03"] = (
            "PASS" if int(total_cast) <= int(reference_registered) else "FAIL"
        )
    if reference_registered is not None and registered_form is not None:
        checks["V07"] = (
            "PASS" if int(registered_form) == int(reference_registered) else "FAIL"
        )
    return checks


def _engine_set(mode: str, settings: Settings) -> list[PageTextEngine]:
    normalized = mode.lower().strip()
    if normalized == "embedded":
        return []
    if normalized in {"tesseract", "local"}:
        engine = TesseractEngine()
        return [engine] if engine.available() else []
    if normalized in {"gcv", "google"}:
        return [GoogleVisionPageEngine(settings.gcv_credentials_json)]
    if normalized in {"textract", "aws"}:
        return [TextractPageEngine(settings.aws_region)]
    if normalized in {"dual", "dual-cloud", "gcv-textract"}:
        return [
            GoogleVisionPageEngine(settings.gcv_credentials_json),
            TextractPageEngine(settings.aws_region),
        ]
    if normalized == "auto":
        # FIX (13/14 Jul 2026 dashboard review): "auto" used to be grouped
        # with tesseract/local above and meant "Tesseract only," full stop --
        # even when real GCV/AWS credentials were configured, they were
        # never even looked at. Handwritten Form 35A digits are exactly what
        # Tesseract (tuned for printed text) reads worst and what GCV/
        # Textract read comparatively well; "auto" now means "use whichever
        # real engines are actually configured, in preference order, and
        # fail over to Tesseract rather than crash the run if a cloud
        # engine's credentials are present but invalid or its package isn't
        # installed."
        engines: list[PageTextEngine] = []
        if settings.gcv_credentials_json:
            try:
                engines.append(GoogleVisionPageEngine(settings.gcv_credentials_json))
            except Exception as exc:  # missing package, bad/expired credentials file, etc.
                logging.getLogger(__name__).warning("auto mode: GCV unavailable (%s)", exc)
        if os.environ.get("AWS_ACCESS_KEY_ID"):
            try:
                engines.append(TextractPageEngine(settings.aws_region))
            except Exception as exc:  # missing package, etc. -- bad keys surface per-page instead
                logging.getLogger(__name__).warning("auto mode: Textract unavailable (%s)", exc)
        if engines:
            return engines
        tesseract = TesseractEngine()
        return [tesseract] if tesseract.available() else []
    raise ValueError(f"unknown historical OCR engine mode: {mode}")


def _combine_texts(texts: list[OCRText]) -> OCRText:
    usable = [item for item in texts if item.text.strip()]
    if not usable:
        return OCRText(text="", confidence=0.0, engine="none")
    best = max(usable, key=lambda item: (item.confidence, len(item.text)))
    return OCRText(
        text=best.text,
        confidence=best.confidence,
        engine="+".join(item.engine for item in usable),
    )


def _review_csv_rows(extractions: list[dict[str, Any]], candidate_ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for extraction in extractions:
        if extraction.get("form_type") != FORM_35A or not extraction.get("stream_key"):
            continue
        fields = extraction.get("parsed", {}).get("fields", {})
        row: dict[str, Any] = {
            "stream_key": extraction["stream_key"],
            "reported_at": "",
            "form_url": extraction.get("public_url") or extraction.get("source_path") or "",
            "verification": "HUMAN",
            "registered_form": fields.get("registered", {}).get("value") or "",
            "rejected": fields.get("rejected", {}).get("value") or "",
            "po_total_valid": fields.get("total_valid", {}).get("value") or "",
            "total_cast_form": fields.get("total_cast", {}).get("value") or "",
            "reviewer_a": "",
            "reviewer_b": "",
            "notes": (
                f"OCR prefill only; status={extraction.get('route')}; engine={extraction.get('engine')}; "
                f"confidence={extraction.get('confidence', 0):.3f}; source={extraction.get('source_path')}; "
                f"page={extraction.get('page_no')}"
            ),
            "ocr_confidence": f"{float(extraction.get('confidence', 0.0)):.4f}",
            "ocr_route": extraction.get("route"),
            "source_sha256": extraction.get("source_sha256"),
            "source_page": extraction.get("page_no"),
        }
        for candidate_id in candidate_ids:
            value = fields.get(f"candidate_{candidate_id}", {}).get("value")
            row[candidate_id] = value if value is not None else ""
        rows.append(row)
    rows.sort(key=lambda row: str(row["stream_key"]))
    return rows


def _write_review_csv(path: Path, rows: list[dict[str, Any]], candidate_ids: list[str]) -> None:
    fieldnames = [
        "stream_key",
        "reported_at",
        "form_url",
        "verification",
        "registered_form",
        *candidate_ids,
        "rejected",
        "po_total_valid",
        "total_cast_form",
        "reviewer_a",
        "reviewer_b",
        "notes",
        "ocr_confidence",
        "ocr_route",
        "source_sha256",
        "source_page",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _numeric_extraction_confidence(
    parsed: dict[str, Any], candidate_ids: list[str], fallback: float
) -> float:
    fields = parsed.get("fields", {})
    required = [
        *(f"candidate_{candidate_id}" for candidate_id in candidate_ids),
        "registered",
        "rejected",
        "total_valid",
        "total_cast",
    ]
    present = [
        float(fields.get(field, {}).get("confidence", 0.0) or 0.0)
        for field in required
        if fields.get(field, {}).get("value") is not None
    ]
    if not present:
        return max(0.0, min(1.0, fallback * 0.35))
    completeness = len(present) / len(required)
    return max(0.0, min(0.99, mean(present) * completeness))


def run_historical_ocr(
    bundle: Any,
    settings: Settings,
    *,
    engine_mode: str = "auto",
    extra_paths: Iterable[Path] | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    inventory = inventory_documents(bundle, extra_paths)
    ocr_dir = bundle.election_dir / "ocr"
    extraction_dir = ocr_dir / "extractions"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    engines = _engine_set(engine_mode, settings)
    candidate_ids = [str(candidate["id"]) for candidate in bundle.candidates]
    candidate_list_complete = bool(bundle.profile.get("ocr", {}).get("candidate_list_complete", True))
    benchmark_only = bool(bundle.profile.get("ocr", {}).get("benchmark_only", False))
    extractions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    layout_assisted_pages = 0

    for document in inventory["documents"]:
        source = bundle.root / document["path"] if not Path(document["path"]).is_absolute() else Path(document["path"])
        for page_no in range(1, int(document["pages"]) + 1):
            page_id = f"{document['sha256'][:16]}-p{page_no:03d}"
            output_path = extraction_dir / f"{page_id}.json"
            if output_path.exists() and not rebuild:
                existing = _read_json(output_path)
                if existing.get("pipeline_version") == OCR_PIPELINE_VERSION:
                    extractions.append(existing)
                    if existing.get("parsed", {}).get("handwriting"):
                        layout_assisted_pages += 1
                    continue
            try:
                with tempfile.TemporaryDirectory(prefix=f"historical-ocr-{page_id}-") as temp:
                    temp_dir = Path(temp)
                    page_image: Path | None = None
                    embedded = _embedded_text(source, page_no)
                    texts: list[OCRText] = []
                    if embedded:
                        texts.append(OCRText(text=embedded, confidence=0.99, engine="embedded-pdf"))
                    needs_ocr = len(re.sub(r"\s+", "", embedded)) < 80
                    if needs_ocr and engines:
                        page_image = _render_page(source, page_no, temp_dir)
                        for engine in engines:
                            try:
                                texts.append(engine.read(page_image))
                            except Exception as exc:
                                errors.append(
                                    {
                                        "page_id": page_id,
                                        "engine": engine.name,
                                        "message": str(exc),
                                    }
                                )
                    combined = _combine_texts(texts)
                    form_type = classify_form(combined.text, document["filename"])
                    reference, match_method = match_stream(bundle, combined.text, document["filename"])
                    parsed: dict[str, Any]
                    checks: dict[str, str] = {}
                    confidence = combined.confidence
                    if form_type == FORM_35A:
                        parsed = parse_form35a(combined.text, bundle.candidates)
                        try:
                            # Handwritten values are isolated from their numeric
                            # cells after printed labels have anchored the row.
                            # This prevents row numbers and ballot numbers from
                            # being mistaken for candidate votes.
                            if page_image is None:
                                page_image = _render_page(source, page_no, temp_dir)
                            cell_result = extract_form35a_numeric_cells(
                                page_image, bundle.candidates, reference
                            )
                            parsed = reconcile_form35a_fields(
                                parsed,
                                cell_result,
                                reference,
                                candidate_ids,
                                candidate_list_complete=candidate_list_complete,
                            )
                            layout_assisted_pages += 1
                        except Exception as exc:
                            # The old full-page extraction remains available as a
                            # fallback. A single difficult scan must not abort the
                            # entire constituency batch.
                            errors.append(
                                {
                                    "page_id": page_id,
                                    "engine": "layout-handwriting",
                                    "message": str(exc),
                                }
                            )
                        checks = _checks_for_extraction(
                            parsed,
                            reference,
                            candidate_ids,
                            candidate_list_complete=candidate_list_complete,
                        )
                        critical = [checks[code] for code in ("V01", "V02", "V03", "V07")]
                        complete = all(
                            parsed["fields"].get(f"candidate_{candidate_id}", {}).get("value") is not None
                            for candidate_id in candidate_ids
                        ) and all(
                            parsed["fields"].get(field, {}).get("value") is not None
                            for field in ("registered", "rejected", "total_valid", "total_cast")
                        )
                        if (
                            benchmark_only
                            and complete
                            and checks["V02"] == "PASS"
                            and checks["V03"] in {"PASS", "NOT_RUN"}
                        ):
                            route = "OCR_BENCHMARK_REVIEW"
                        else:
                            route = (
                                "READY_FOR_DOUBLE_REVIEW"
                                if reference is not None
                                and complete
                                and all(status == "PASS" for status in critical)
                                else "QUARANTINE"
                            )
                        confidence = _numeric_extraction_confidence(
                            parsed, candidate_ids, combined.confidence
                        )
                    elif form_type == FORM_35B:
                        parsed = parse_form35b(combined.text, bundle.candidates)
                        route = "FORM_35B_REVIEW"
                    else:
                        parsed = {}
                        route = "UNCLASSIFIED"
                    extraction = {
                        "schema": "kenya.election.ocr-extraction.v1",
                        "pipeline_version": OCR_PIPELINE_VERSION,
                        "election_id": bundle.election_id,
                        "page_id": page_id,
                        "source_path": document["path"],
                        "source_sha256": document["sha256"],
                        "source_filename": document["filename"],
                        "public_url": (
                            f"{document.get('public_url')}#page={page_no}"
                            if document.get("public_url") and document.get("extension") == ".pdf"
                            else document.get("public_url")
                        ),
                        "page_no": page_no,
                        "form_type": form_type,
                        "stream_key": str(reference["stream_key"]) if reference else None,
                        "match_method": match_method,
                        "engine": combined.engine + ("+layout-handwriting" if parsed.get("handwriting") else ""),
                        "confidence": confidence,
                        "text_length": len(combined.text),
                        "text_preview": combined.text[:3000],
                        "parsed": parsed,
                        "checks": checks,
                        "route": route,
                        "auto_published": False,
                        "extracted_at": utc_now_iso(),
                    }
                    _write_json(output_path, extraction)
                    extractions.append(extraction)
            except Exception as exc:
                error = {
                    "page_id": page_id,
                    "source_path": document["path"],
                    "page_no": page_no,
                    "message": str(exc),
                }
                errors.append(error)
                extraction = {
                    "schema": "kenya.election.ocr-extraction.v1",
                    "pipeline_version": OCR_PIPELINE_VERSION,
                    "election_id": bundle.election_id,
                    "page_id": page_id,
                    "source_path": document["path"],
                    "source_sha256": document["sha256"],
                    "source_filename": document["filename"],
                    "page_no": page_no,
                    "form_type": OTHER,
                    "stream_key": None,
                    "match_method": None,
                    "engine": "error",
                    "confidence": 0.0,
                    "text_length": 0,
                    "text_preview": "",
                    "parsed": {},
                    "checks": {},
                    "route": "ERROR",
                    "auto_published": False,
                    "error": str(exc),
                    "extracted_at": utc_now_iso(),
                }
                _write_json(output_path, extraction)
                extractions.append(extraction)

    review_rows = _review_csv_rows(extractions, candidate_ids)
    _write_review_csv(ocr_dir / "review_queue.csv", review_rows, candidate_ids)
    form35b_rows = [row for row in extractions if row.get("form_type") == FORM_35B]
    _write_json(
        ocr_dir / "form35b_review.json",
        {
            "schema": "kenya.election.form35b-ocr-review.v1",
            "election_id": bundle.election_id,
            "generated_at": utc_now_iso(),
            "forms": form35b_rows,
        },
    )
    routes: dict[str, int] = {}
    for row in extractions:
        route = str(row.get("route") or "UNKNOWN")
        routes[route] = routes.get(route, 0) + 1
    summary = {
        "schema": "kenya.election.ocr-summary.v1",
        "pipeline_version": OCR_PIPELINE_VERSION,
        "election_id": bundle.election_id,
        "generated_at": utc_now_iso(),
        "engine_mode": engine_mode,
        "engines_available": [engine.name for engine in engines],
        "documents_total": inventory["documents_total"],
        "pages_total": inventory["pages_total"],
        "pages_processed": len(extractions),
        "layout_assisted_pages": layout_assisted_pages,
        "form35a_detected": sum(1 for row in extractions if row.get("form_type") == FORM_35A),
        "form35b_detected": len(form35b_rows),
        "streams_matched": len(
            {row["stream_key"] for row in extractions if row.get("stream_key")}
        ),
        "review_rows": len(review_rows),
        "routes": routes,
        "errors": errors,
        "review_queue": _relative(ocr_dir / "review_queue.csv", bundle.root),
        "inventory": _relative(ocr_dir / "document_inventory.json", bundle.root),
        "auto_publication": False,
        "note": (
            "OCR output is a pre-fill only. Handwritten cells are read with layout anchors and "
            "arithmetic reconciliation, but no historical stream is added to the public tally until "
            "human review and statutory validation are complete."
        ),
    }
    _write_json(ocr_dir / "summary.json", summary)
    return summary


def load_ocr_summary(bundle: Any) -> dict[str, Any]:
    path = bundle.election_dir / "ocr" / "summary.json"
    if not path.exists():
        return {
            "schema": "kenya.election.ocr-summary.v1",
            "pipeline_version": OCR_PIPELINE_VERSION,
            "election_id": bundle.election_id,
            "generated_at": None,
            "engine_mode": None,
            "engines_available": [],
            "documents_total": 0,
            "pages_total": 0,
            "pages_processed": 0,
            "form35a_detected": 0,
            "form35b_detected": 0,
            "streams_matched": 0,
            "review_rows": 0,
            "routes": {},
            "errors": [],
            "auto_publication": False,
            "note": "Historical OCR has not been run for this election.",
        }
    return _read_json(path)


def load_ocr_stream_extractions(bundle: Any) -> dict[str, dict[str, Any]]:
    extraction_dir = bundle.election_dir / "ocr" / "extractions"
    if not extraction_dir.exists():
        return {}
    output: dict[str, dict[str, Any]] = {}
    for path in sorted(extraction_dir.glob("*.json")):
        row = _read_json(path)
        stream_key = row.get("stream_key")
        if not stream_key or row.get("form_type") != FORM_35A:
            continue
        current = output.get(str(stream_key))
        if current is None or float(row.get("confidence", 0.0)) > float(current.get("confidence", 0.0)):
            output[str(stream_key)] = row
    return output


def tesseract_install_hint() -> dict[str, Any]:
    command = shutil.which("tesseract")
    version = None
    if command:
        try:
            version = subprocess.run(
                [command, "--version"], capture_output=True, text=True, check=False
            ).stdout.splitlines()[0]
        except Exception:
            version = None
    return {
        "available": bool(command),
        "path": command,
        "version": version,
        "windows_install": "winget install --id UB-Mannheim.TesseractOCR --exact",
    }
