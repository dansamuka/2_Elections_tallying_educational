from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _clean_name(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", value or "").strip(" -:|/.,_")
    text = re.sub(r"\bPOLLING\s+STATION\b", "", text, flags=re.I)
    text = re.sub(r"\b(?:STREAM\s*)?0?\d{1,2}\s*(?:OF|/)?\s*\d{0,2}\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -:|/.,_")
    return text.upper()[:180] or None


def _spaced_code_candidates(text: str, prefix: str) -> list[str]:
    # OCR sometimes inserts spaces between individual digits. Capture exactly
    # the remaining nine digits after the six-digit county/constituency prefix.
    spaced_prefix = "".join(re.escape(digit) + r"\s*" for digit in prefix)
    pattern = re.compile(
        rf"(?<!\d){spaced_prefix}(?P<tail>(?:\d\s*){{9}})(?!\d)",
        re.I,
    )
    output: list[str] = []
    for match in pattern.finditer(text):
        tail = re.sub(r"\D", "", match.group("tail"))
        code = prefix + tail
        if len(code) == 15:
            output.append(code)
    return output


@dataclass(frozen=True)
class Form35AIdentity:
    polling_station_code: str | None
    constituency_code: str | None
    ward_code: str | None
    polling_centre_code: str | None
    stream_no: int | None
    ward_name: str | None
    polling_centre_name: str | None
    confidence: float
    evidence: list[str]

    @property
    def stream_key(self) -> str | None:
        if not (
            self.constituency_code
            and self.ward_code
            and self.polling_centre_code
            and self.stream_no is not None
        ):
            return None
        return (
            f"{self.constituency_code}-{self.ward_code}-"
            f"{self.polling_centre_code}-{self.stream_no:02d}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "kenya.election.form35a-identity.v1",
            "polling_station_code": self.polling_station_code,
            "constituency_code": self.constituency_code,
            "ward_code": self.ward_code,
            "polling_centre_code": self.polling_centre_code,
            "stream_no": self.stream_no,
            "stream_key": self.stream_key,
            "ward_name": self.ward_name,
            "polling_centre_name": self.polling_centre_name,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


def parse_form35a_identity(
    text: str,
    *,
    county_code: str,
    constituency_code: str,
    portal_station_name: str | None = None,
    portal_ward_name: str | None = None,
) -> Form35AIdentity:
    """Extract printed hierarchy fields from a Form 35A header.

    These fields are printed, not handwritten, and are therefore much more
    reliable than candidate-vote OCR. The 15-digit station code is treated as
    the strongest identity: county(3) + constituency(3) + ward(4) + centre(3)
    + stream(2). No result figures are trusted or published by this helper.
    """
    raw = text or ""
    flat = re.sub(r"[\t\r]+", " ", raw)
    prefix = f"{str(county_code).zfill(3)}{str(constituency_code).zfill(3)}"
    codes = re.findall(rf"(?<!\d)({re.escape(prefix)}\d{{9}})(?!\d)", flat)
    codes.extend(_spaced_code_candidates(flat, prefix))
    # Preserve order while deduplicating.
    codes = list(dict.fromkeys(codes))
    code = codes[0] if codes else None

    ward_name = None
    ward_match = re.search(
        r"\bWARD\s+([A-Z][A-Z0-9'’&./ -]{1,80}?)\s+(?:CODE|C0DE|COOE|Constituency)\b",
        flat,
        re.I,
    )
    if ward_match:
        ward_name = _clean_name(ward_match.group(1))
    if not ward_name:
        ward_match = re.search(
            r"\bWARD\s+([A-Z][A-Z0-9'’&./ -]{1,80}?)\s+CONSTITUENCY\b",
            flat,
            re.I,
        )
        if ward_match:
            ward_name = _clean_name(ward_match.group(1))
    ward_name = ward_name or _clean_name(portal_ward_name)

    station_name = None
    station_match = re.search(
        r"NAME\s+OF\s+POLLING\s+STATION\s+(.{3,180}?)(?:\bWARD\b|\bCODE\b|\bC0DE\b|\bConstituency\b)",
        flat,
        re.I | re.S,
    )
    if station_match:
        station_name = _clean_name(station_match.group(1))
    station_name = station_name or _clean_name(portal_station_name)

    ward_code = code[6:10] if code else None
    centre_code = code[10:13] if code else None
    stream_no = int(code[13:15]) if code else None
    evidence: list[str] = []
    if code:
        evidence.append(f"printed station code {code}")
    if ward_name:
        evidence.append(f"printed/portal ward {ward_name}")
    if station_name:
        evidence.append(f"printed/portal centre {station_name}")
    confidence = 0.98 if code and ward_name and station_name else 0.93 if code else 0.65 if ward_name else 0.0
    return Form35AIdentity(
        polling_station_code=code,
        constituency_code=str(constituency_code).zfill(3) if code else None,
        ward_code=ward_code,
        polling_centre_code=centre_code,
        stream_no=stream_no,
        ward_name=ward_name,
        polling_centre_name=station_name,
        confidence=confidence,
        evidence=evidence,
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ward_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("ward_code") or "UNRESOLVED"), str(row.get("ward_name") or "WARD TO VERIFY"))
        groups.setdefault(key, []).append(row)
    output = []
    for (code, name), members in groups.items():
        registered = [member.get("registered") for member in members]
        output.append({
            "code": code,
            "name": name,
            "streams": len(members),
            "registered": sum(int(value) for value in registered) if members and all(value is not None for value in registered) else None,
            "reference_state": "FORM_HEADER_OCR" if code != "UNRESOLVED" else "PORTAL_BOOTSTRAP",
        })
    return sorted(output, key=lambda row: (row["name"], row["code"]))


def reconcile_bootstrap_hierarchy(
    bundle: Any,
    extractions: Iterable[dict[str, Any]],
    *,
    persist_extractions: bool = True,
) -> dict[str, Any]:
    """Replace synthetic Malava bootstrap identities with form-header identities.

    The mapping is source-hash based, so even OCR pages that were not initially
    matched to a synthetic stream can be attached to the exact portal assignment.
    The resulting register remains *uncertified* and review-only; this function
    improves navigation/provenance, not publication authority.
    """
    if not bool(bundle.streams_doc.get("bootstrap_from_portal")):
        return {"changed": False, "mapped": 0, "unresolved": 0, "errors": []}

    manifest = bundle.manifest_path.exists() and json.loads(bundle.manifest_path.read_text(encoding="utf-8")) or {
        "schema": "kenya.election.forms-manifest.v1",
        "election_id": bundle.election_id,
        "forms": {},
    }
    manifest_items = list(manifest.get("forms", {}).values())
    manifest_by_sha = {
        str(item.get("sha256")): item for item in manifest_items if item.get("sha256")
    }
    rows = list(bundle.streams_doc.get("streams", []))
    rows_by_url = {
        str(row.get("portal_source_url")): row for row in rows if row.get("portal_source_url")
    }
    rows_by_key = {str(row.get("stream_key")): row for row in rows if row.get("stream_key")}
    used_keys = {str(row.get("stream_key")) for row in rows if row.get("stream_key")}
    used_codes = {str(row.get("polling_station_code")) for row in rows if row.get("polling_station_code")}
    mapped = 0
    changed = False
    errors: list[dict[str, str]] = []
    extraction_rows = list(extractions)

    for extraction in extraction_rows:
        identity = extraction.get("form_identity") or {}
        code = identity.get("polling_station_code")
        new_key = identity.get("stream_key")
        if not code or not new_key:
            continue
        manifest_item = manifest_by_sha.get(str(extraction.get("source_sha256")))
        source_url = str((manifest_item or {}).get("source_url") or "")
        old_key = str((manifest_item or {}).get("stream_key") or extraction.get("stream_key") or "")
        row = rows_by_url.get(source_url) or rows_by_key.get(old_key)
        if row is None:
            station_norm = _norm(identity.get("polling_centre_name"))
            stream_no = identity.get("stream_no")
            candidates = [
                candidate for candidate in rows
                if _norm(candidate.get("station_name")) == station_norm
                and int(candidate.get("stream_no") or 0) == int(stream_no or 0)
            ]
            row = candidates[0] if len(candidates) == 1 else None
        if row is None:
            errors.append({"page_id": str(extraction.get("page_id")), "message": "form header identity could not be tied to a portal assignment"})
            continue

        previous_key = str(row.get("stream_key") or "")
        previous_code = str(row.get("polling_station_code") or "")
        if new_key != previous_key and new_key in used_keys:
            errors.append({"page_id": str(extraction.get("page_id")), "message": f"duplicate official stream key {new_key}"})
            continue
        if code != previous_code and code in used_codes:
            errors.append({"page_id": str(extraction.get("page_id")), "message": f"duplicate official polling-station code {code}"})
            continue

        if previous_key:
            used_keys.discard(previous_key)
            rows_by_key.pop(previous_key, None)
        if previous_code:
            used_codes.discard(previous_code)
        row.update({
            "stream_key": new_key,
            "polling_station_code": code,
            "polling_centre_code": identity.get("polling_centre_code"),
            "station_name": identity.get("polling_centre_name") or row.get("station_name"),
            "polling_centre_name": identity.get("polling_centre_name") or row.get("polling_centre_name") or row.get("station_name"),
            "stream_no": int(identity.get("stream_no")),
            "ward_code": identity.get("ward_code") or row.get("ward_code") or "UNRESOLVED",
            "ward_name": identity.get("ward_name") or row.get("ward_name") or "WARD TO VERIFY",
            "reference_state": "FORM_HEADER_OCR",
            "identity_confidence": identity.get("confidence"),
            "identity_evidence": identity.get("evidence", []),
        })
        used_keys.add(new_key)
        used_codes.add(code)
        rows_by_key[new_key] = row
        if source_url:
            rows_by_url[source_url] = row
        if manifest_item is not None:
            manifest_item.update({
                "stream_key": new_key,
                "polling_station_code": code,
                "ward_code": row.get("ward_code"),
                "ward_name": row.get("ward_name"),
                "polling_centre_code": row.get("polling_centre_code"),
                "polling_centre_name": row.get("polling_centre_name"),
                "hierarchy_source": "FORM_HEADER_OCR",
            })
        extraction["stream_key"] = new_key
        extraction["match_method"] = "FORM_HEADER_CODE"
        extraction["form_identity"]["applied_to_register"] = True
        mapped += 1
        changed = True

    # Fill names across streams sharing a ward code when one difficult scan did
    # not OCR the name cleanly but another stream in the same ward did.
    ward_names: dict[str, str] = {}
    for row in rows:
        code = str(row.get("ward_code") or "")
        name = str(row.get("ward_name") or "")
        if code and code != "UNRESOLVED" and name and name != "WARD TO VERIFY":
            ward_names.setdefault(code, name)
    for row in rows:
        code = str(row.get("ward_code") or "")
        if code in ward_names and row.get("ward_name") in {None, "", "WARD TO VERIFY"}:
            row["ward_name"] = ward_names[code]
            changed = True

    rows.sort(key=lambda row: (
        str(row.get("ward_name") or ""),
        str(row.get("station_name") or ""),
        int(row.get("stream_no") or 0),
        str(row.get("stream_key") or ""),
    ))
    bundle.streams_doc["streams"] = rows
    bundle.streams_doc["ward_summary"] = _ward_summary(rows)
    bundle.streams_doc["hierarchy_reconciled_from_forms"] = mapped
    if mapped:
        bundle.streams_doc["reference_verified"] = False
        notes = list(bundle.streams_doc.get("notes", []))
        message = (
            "Polling-centre and ward hierarchy was reconstructed from the printed Form 35A header. "
            "This improves navigation but remains uncertified and cannot drive publication."
        )
        if message not in notes:
            notes.append(message)
        bundle.streams_doc["notes"] = notes

    if changed:
        _write_json(bundle.election_dir / "streams.json", bundle.streams_doc)
        _write_json(bundle.manifest_path, manifest)
        if persist_extractions:
            extraction_dir = bundle.election_dir / "ocr" / "extractions"
            for extraction in extraction_rows:
                page_id = extraction.get("page_id")
                if page_id:
                    _write_json(extraction_dir / f"{page_id}.json", extraction)

    return {
        "changed": changed,
        "mapped": mapped,
        "unresolved": sum(1 for row in rows if row.get("ward_code") in {None, "", "UNRESOLVED"}),
        "errors": errors,
    }


def reconcile_existing_bootstrap_hierarchy(bundle: Any) -> dict[str, Any]:
    extraction_dir = bundle.election_dir / "ocr" / "extractions"
    extractions: list[dict[str, Any]] = []
    manifest = {}
    if bundle.manifest_path.exists():
        try:
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    manifest_by_sha = {
        str(item.get("sha256")): item
        for item in manifest.get("forms", {}).values()
        if item.get("sha256")
    }
    references = {
        str(row.get("stream_key")): row
        for row in bundle.streams_doc.get("streams", [])
        if row.get("stream_key")
    }
    if extraction_dir.exists():
        for path in sorted(extraction_dir.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if row.get("text_preview") and not row.get("form_identity"):
                manifest_item = manifest_by_sha.get(str(row.get("source_sha256")), {})
                reference = references.get(str(row.get("stream_key") or ""), {})
                identity = parse_form35a_identity(
                    str(row.get("text_preview") or ""),
                    county_code=str(bundle.profile.get("election", {}).get("county_code", "000")),
                    constituency_code=str(bundle.profile.get("election", {}).get("code", "000")),
                    portal_station_name=reference.get("station_name")
                    or manifest_item.get("polling_centre_name")
                    or manifest_item.get("source_label"),
                    portal_ward_name=reference.get("ward_name") or manifest_item.get("ward_name"),
                )
                row["form_identity"] = identity.as_dict()
            extractions.append(row)
    return reconcile_bootstrap_hierarchy(bundle, extractions)

