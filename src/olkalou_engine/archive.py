from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .historical_ocr import load_ocr_stream_extractions, load_ocr_summary
from .portal import PortalClient, extension_from_response


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


@dataclass(frozen=True)
class HistoricalBundle:
    root: Path
    election_id: str
    profile: dict[str, Any]
    streams_doc: dict[str, Any]

    @property
    def election_dir(self) -> Path:
        return self.root / "data" / "elections" / self.election_id

    @property
    def public_path(self) -> Path:
        return self.root / "data" / "public" / "elections" / f"{self.election_id}.json"

    @property
    def manifest_path(self) -> Path:
        return self.election_dir / "forms_manifest.json"

    @property
    def verified_results_path(self) -> Path:
        return self.election_dir / "verified_results.json"

    @property
    def streams(self) -> list[dict[str, Any]]:
        return list(self.streams_doc.get("streams", []))

    @property
    def candidates(self) -> list[dict[str, Any]]:
        return list(self.profile.get("candidates", []))


def load_historical_bundle(root: Path, election_id: str) -> HistoricalBundle:
    root = root.resolve()
    election_dir = root / "data" / "elections" / election_id
    profile_path = election_dir / "election.json"
    streams_path = election_dir / "streams.json"
    if not profile_path.exists() or not streams_path.exists():
        raise FileNotFoundError(f"historical election {election_id!r} is not configured")
    bundle = HistoricalBundle(
        root=root,
        election_id=election_id,
        profile=_read_json(profile_path),
        streams_doc=_read_json(streams_path),
    )
    validate_historical_bundle(bundle)
    return bundle


def validate_historical_bundle(bundle: HistoricalBundle) -> None:
    profile = bundle.profile
    streams = bundle.streams
    if profile.get("id") != bundle.election_id:
        raise ValueError("profile id does not match directory/election id")
    expected = int(profile["register"]["streams_total"])
    register_total = int(profile["register"]["total"])
    reference_verified = bool(profile.get("register", {}).get("verified", True))
    live_mode = str(profile.get("mode", "ARCHIVE")).upper() == "LIVE"
    if len(streams) != expected:
        raise ValueError(f"expected {expected} streams, found {len(streams)}")
    keys = [str(row["stream_key"]) for row in streams]
    codes = [str(row["polling_station_code"]) for row in streams]
    if len(set(keys)) != len(keys):
        raise ValueError("historical stream keys must be unique")
    if len(set(codes)) != len(codes):
        raise ValueError("historical polling-station codes must be unique")
    known_registered = [row.get("registered") for row in streams if row.get("registered") is not None]
    if len(known_registered) == len(streams):
        actual_total = sum(int(value) for value in known_registered)
        if actual_total != register_total:
            raise ValueError(f"register total mismatch: {actual_total} != {register_total}")
    elif reference_verified or not live_mode:
        raise ValueError("verified historical profiles require registered voters for every stream")
    candidate_ids = [str(c["id"]) for c in bundle.candidates]
    if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate ids must be present and unique")


def load_manifest(bundle: HistoricalBundle) -> dict[str, Any]:
    if bundle.manifest_path.exists():
        return _read_json(bundle.manifest_path)
    return {"schema": "kenya.election.forms-manifest.v1", "election_id": bundle.election_id, "forms": {}}


def _load_results(bundle: HistoricalBundle) -> dict[str, dict[str, Any]]:
    if not bundle.verified_results_path.exists():
        return {}
    doc = _read_json(bundle.verified_results_path)
    return {str(row["stream_key"]): row for row in doc.get("results", [])}


def _checks_for_row(row: dict[str, Any], registered: int, candidate_ids: list[str]) -> dict[str, str]:
    votes = {candidate_id: int(row["votes"][candidate_id]) for candidate_id in candidate_ids}
    valid = sum(votes.values())
    rejected = int(row["rejected"])
    cast = valid + rejected
    checks = {
        "V01": "PASS" if valid == int(row["po_total_valid"]) else "FAIL",
        "V02": "PASS" if cast == int(row["total_cast_form"]) else "FAIL",
        "V03": "PASS" if cast <= registered else "FAIL",
        "V07": "PASS" if int(row["registered_form"]) == registered else "FAIL",
    }
    return checks


def import_verified_results(bundle: HistoricalBundle, csv_path: Path) -> dict[str, Any]:
    candidate_ids = [str(c["id"]) for c in bundle.candidates]
    references = {str(s["stream_key"]): s for s in bundle.streams}
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "stream_key", "reported_at", "form_url", "verification", "registered_form",
            "rejected", "po_total_valid", "total_cast_form", *candidate_ids,
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"results CSV is missing columns: {', '.join(sorted(missing))}")
        for line_no, raw in enumerate(reader, start=2):
            stream_key = (raw.get("stream_key") or "").strip()
            # Blank template rows are ignored until figures are entered.
            if not stream_key or all(not (raw.get(cid) or "").strip() for cid in candidate_ids):
                continue
            if stream_key not in references:
                raise ValueError(f"line {line_no}: unknown stream_key {stream_key}")
            if stream_key in seen:
                raise ValueError(f"line {line_no}: duplicate stream_key {stream_key}")
            seen.add(stream_key)
            votes = {cid: int(raw[cid]) for cid in candidate_ids}
            row = {
                "stream_key": stream_key,
                "reported_at": (raw.get("reported_at") or "").strip() or None,
                "form_url": (raw.get("form_url") or "").strip() or None,
                "verification": (raw.get("verification") or "HUMAN").strip().upper(),
                "registered_form": int(raw["registered_form"]),
                "votes": votes,
                "rejected": int(raw["rejected"]),
                "po_total_valid": int(raw["po_total_valid"]),
                "total_cast_form": int(raw["total_cast_form"]),
                "reviewer_a": (raw.get("reviewer_a") or "").strip() or None,
                "reviewer_b": (raw.get("reviewer_b") or "").strip() or None,
                "notes": (raw.get("notes") or "").strip() or None,
            }
            reference_registered = references[stream_key].get("registered")
            if reference_registered is None:
                raise ValueError(
                    f"line {line_no}: stream reference is unresolved; certify its registered-voter row before publication"
                )
            checks = _checks_for_row(row, int(reference_registered), candidate_ids)
            failed = [code for code, status in checks.items() if status == "FAIL"]
            if failed:
                raise ValueError(f"line {line_no}: statutory checks failed: {', '.join(failed)}")
            if row["verification"] not in {"HUMAN", "MACHINE"}:
                raise ValueError(f"line {line_no}: verification must be HUMAN or MACHINE")
            row["checks"] = checks
            results.append(row)
    doc = {
        "schema": "kenya.election.verified-results.v1",
        "election_id": bundle.election_id,
        "imported_at": utc_now_iso(),
        "source_csv": str(csv_path),
        "results": results,
    }
    _write_json(bundle.verified_results_path, doc)
    return doc


def _manifest_by_stream(bundle: HistoricalBundle) -> dict[str, dict[str, Any]]:
    manifest = load_manifest(bundle)
    output: dict[str, dict[str, Any]] = {}
    for item in manifest.get("forms", {}).values():
        stream_key = item.get("stream_key")
        if stream_key:
            output[str(stream_key)] = item
    return output


def _load_sync_status(bundle: HistoricalBundle) -> dict[str, Any]:
    path = bundle.election_dir / "sync_status.json"
    if not path.exists():
        return {
            "schema": "kenya.election.portal-sync.v1",
            "election_id": bundle.election_id,
            "state": "NEVER_RUN",
            "last_completed_at": None,
            "last_changed_at": None,
            "message": "The IEBC portal sync has not run for this election.",
        }
    return _read_json(path)


def _ocr_prefill(ocr_record: dict[str, Any] | None, candidate_ids: list[str]) -> dict[str, Any] | None:
    """Surfaces the raw, per-candidate OCR-extracted figures for a stream
    that hasn't been independently verified yet -- namespaced under
    stream.ocr.prefill_* in the public payload, never under stream.votes.
    stream.votes stays reserved for statutorily-checked, human-reviewed
    figures (see import_verified_results / _checks_for_row above); this is
    additive, source-linked, honestly-labelled evidence for someone
    reviewing a specific stream against its actual scanned form, not a
    result. Returns None if there's nothing to show (no OCR record, or the
    parser found no numeric fields on the page).
    """
    if not ocr_record:
        return None
    fields = (ocr_record.get("parsed") or {}).get("fields", {})

    votes: dict[str, int] = {}
    for cid in candidate_ids:
        value = fields.get(f"candidate_{cid}", {}).get("value")
        if value is not None:
            votes[cid] = int(value)

    def _field(name: str) -> int | None:
        value = fields.get(name, {}).get("value")
        return int(value) if value is not None else None

    prefill = {
        "votes": votes or None,
        "registered": _field("registered"),
        "rejected": _field("rejected"),
        "total_valid": _field("total_valid"),
        "total_cast": _field("total_cast"),
    }
    if not any(prefill.values()):
        return None
    return prefill


def build_archive_payload(bundle: HistoricalBundle) -> dict[str, Any]:
    results = _load_results(bundle)
    manifest_by_stream = _manifest_by_stream(bundle)
    candidate_ids = [str(c["id"]) for c in bundle.candidates]
    official = bundle.profile.get("official_declaration", {})
    ocr_summary = load_ocr_summary(bundle)
    ocr_by_stream = load_ocr_stream_extractions(bundle)
    sync_status = _load_sync_status(bundle)
    manifest = load_manifest(bundle)
    archived_stream_keys = set(manifest_by_stream) | set(ocr_by_stream)
    stream_payloads: list[dict[str, Any]] = []
    candidate_totals = {cid: 0 for cid in candidate_ids}
    published_registered = 0
    published_valid = 0
    published_rejected = 0
    replay_events: list[dict[str, Any]] = []

    for reference in bundle.streams:
        stream_key = str(reference["stream_key"])
        result = results.get(stream_key)
        archived = manifest_by_stream.get(stream_key)
        if result:
            votes = {cid: int(result["votes"].get(cid, 0)) for cid in candidate_ids}
            valid = sum(votes.values())
            rejected = int(result["rejected"])
            cast = valid + rejected
            registered = int(reference["registered"])
            for cid, value in votes.items():
                candidate_totals[cid] += value
            published_registered += registered
            published_valid += valid
            published_rejected += rejected
            payload = {
                "stream_key": stream_key,
                "polling_station_code": reference.get("polling_station_code"),
                "station_name": reference["station_name"],
                "stream_no": reference["stream_no"],
                "ward": reference["ward_name"],
                "state": "PUBLISHED",
                "verification": result["verification"],
                "registered": registered,
                "votes": votes,
                "rejected": rejected,
                "valid": valid,
                "cast": cast,
                "turnout": cast / registered if registered else None,
                "checks": result.get("checks", {}),
                "form_url": result.get("form_url") or (archived or {}).get("public_url"),
                "published_at": result.get("reported_at"),
            }
            if result.get("reported_at"):
                replay_events.append({
                    "at": result["reported_at"],
                    "stream_key": stream_key,
                    "votes": votes,
                    "rejected": rejected,
                })
        else:
            ocr_record = ocr_by_stream.get(stream_key)
            state = "OCR_REVIEW" if ocr_record else ("ARCHIVED" if archived else "REFERENCE_ONLY")
            payload = {
                "stream_key": stream_key,
                "polling_station_code": reference.get("polling_station_code"),
                "station_name": reference["station_name"],
                "stream_no": reference["stream_no"],
                "ward": reference["ward_name"],
                "state": state,
                "verification": "NONE",
                "registered": reference["registered"],
                "votes": {},
                "rejected": None,
                "valid": None,
                "cast": None,
                "turnout": None,
                "checks": {},
                "form_url": (ocr_record or {}).get("public_url") or (archived or {}).get("public_url"),
                "ocr": {
                    "route": (ocr_record or {}).get("route"),
                    "confidence": (ocr_record or {}).get("confidence"),
                    "checks": (ocr_record or {}).get("checks", {}),
                    "prefill": _ocr_prefill(ocr_record, candidate_ids),
                } if ocr_record else None,
                "published_at": None,
            }
        stream_payloads.append(payload)

    stream_results_complete = len(results) == len(bundle.streams)
    official_totals = official.get("candidate_totals", {})
    if stream_results_complete:
        tally_source = "FORM_35A_SUM"
    elif official_totals:
        tally_source = "OFFICIAL_DECLARATION"
    else:
        tally_source = "NO_VERIFIED_TALLY"
    if not stream_results_complete:
        candidate_totals = {cid: official_totals.get(cid) for cid in candidate_ids}

    numeric_totals = [value for value in candidate_totals.values() if value is not None]
    valid_votes = sum(numeric_totals) if len(numeric_totals) == len(candidate_ids) else None
    if stream_results_complete:
        valid_votes = published_valid
        rejected_votes: int | None = published_rejected
        total_cast: int | None = published_valid + published_rejected
    else:
        rejected_votes = official.get("rejected_votes")
        total_cast = official.get("total_cast")

    candidates_payload: list[dict[str, Any]] = []
    for candidate in bundle.candidates:
        votes = candidate_totals.get(candidate["id"])
        share = votes / valid_votes if votes is not None and valid_votes else None
        candidates_payload.append({**candidate, "votes": votes, "share": share, "swing_2022": None})
    candidates_payload.sort(key=lambda row: (-(row["votes"] or -1), row.get("ballot_no") or 999))

    replay_events.sort(key=lambda row: row["at"])
    archive_info = {
        "forms_expected": int(bundle.profile["portal"]["expected_forms"]),
        "forms_archived": len(archived_stream_keys),
        "stream_results_transcribed": len(results),
        "stream_results_complete": stream_results_complete,
        "tally_source": tally_source,
        "replay_available": stream_results_complete and len(replay_events) == len(results),
        "replay_events": replay_events if stream_results_complete else [],
        "methodology_note": bundle.profile.get("methodology", {}).get("note"),
        "ocr": ocr_summary,
        "portal_sync": sync_status,
        "portal_discovered": int(manifest.get("discovered_count", 0)),
        "portal_downloaded": int(manifest.get("downloaded_count", 0)),
        "portal_unmatched": len(manifest.get("unmatched", [])),
    }
    coverage = {
        "streams_total": len(bundle.streams),
        "published": len(results),
        "in_review": max(0, len(archived_stream_keys) - len(results)),
        "conflicted": 0,
        "awaiting": max(0, len(bundle.streams) - len(archived_stream_keys)),
        "reference_only": sum(1 for row in stream_payloads if row["state"] == "REFERENCE_ONLY"),
        "archived_untranscribed": sum(1 for row in stream_payloads if row["state"] == "ARCHIVED"),
        "ocr_review": sum(1 for row in stream_payloads if row["state"] == "OCR_REVIEW"),
        "registered_total": int(bundle.profile["register"]["total"]),
        "registered_reported": published_registered,
        "registered_pct": published_registered / int(bundle.profile["register"]["total"]) if published_registered else 0.0,
        "excluded": {"count": 0, "reason": None},
    }
    ward_summary = {
        str(row.get("name", "")).upper(): row
        for row in bundle.streams_doc.get("ward_summary", [])
    }
    ward_rows = []
    for ward in sorted({row["ward_name"] for row in bundle.streams}):
        refs = [row for row in bundle.streams if row["ward_name"] == ward]
        pubs = [row for row in stream_payloads if row["ward"] == ward and row["state"] == "PUBLISHED"]
        known_ward_registered = [row.get("registered") for row in refs if row.get("registered") is not None]
        summary_registered = ward_summary.get(str(ward).upper(), {}).get("registered")
        ward_registered = (
            sum(int(value) for value in known_ward_registered)
            if len(known_ward_registered) == len(refs)
            else summary_registered
        )
        ward_rows.append({
            "code": refs[0]["ward_code"],
            "name": ward,
            "streams_total": len(refs),
            "published": len(pubs),
            "registered": ward_registered,
            "registered_reported": sum(int(row["registered"]) for row in pubs if row.get("registered") is not None),
            "turnout": None,
            "candidates": {cid: sum(int(row["votes"].get(cid, 0)) for row in pubs) for cid in candidate_ids},
        })

    reference_verified = bool(bundle.profile.get("register", {}).get("verified", True))
    reference_errors = [] if reference_verified else [
        "The certified 144-row atomic register is not yet loaded; downloaded forms and OCR remain review-only.",
        "Candidate legal names and Form 35A row order remain subject to final source verification.",
    ]
    profile_mode = str(bundle.profile.get("mode", "ARCHIVE")).upper()
    payload_status = "FINAL" if profile_mode == "ARCHIVE" else (
        "COUNTING" if int(manifest.get("discovered_count", 0)) > 0 else "PRE_POLL"
    )

    payload = {
        "schema": "kenya.election.archive.v1",
        "seq": int(datetime.now(timezone.utc).timestamp() * 1000),
        "generated_at": utc_now_iso(),
        "mode": profile_mode,
        "election_id": bundle.election_id,
        "election": bundle.profile["election"],
        "status": payload_status,
        "reference": {
            "complete": reference_verified,
            "errors": reference_errors,
            "register_source": bundle.profile["register"]["source"],
            "register_source_url": bundle.profile["register"].get("source_url"),
            "candidate_source": bundle.profile.get("candidate_reference", {}).get(
                "source", "Election profile candidate source"
            ),
            "candidate_source_url": bundle.profile.get("candidate_reference", {}).get("source_url"),
            "ballot_order_verified": bundle.profile.get("candidate_reference", {}).get(
                "ballot_order_verified", reference_verified
            ),
        },
        "pipeline_health": {
            "watcher": sync_status.get("state", "NEVER_RUN"),
            "extractor": (
                "OCR_REVIEW_READY" if ocr_summary.get("pages_processed", 0) else "MANUAL_REVIEW"
            ),
            "last_portal_ok": manifest.get("last_portal_ok"),
            "last_sync_completed": sync_status.get("last_completed_at"),
            "last_sync_changed": sync_status.get("last_changed_at"),
            "worker_id": "github-actions-or-manual",
        },
        "coverage": coverage,
        "totals": {
            "valid_votes": valid_votes,
            "rejected_votes": rejected_votes,
            "total_cast": total_cast,
            "turnout_of_reported": (total_cast / coverage["registered_total"]) if total_cast is not None else None,
        },
        "candidates": candidates_payload,
        "blocs": _build_blocs(bundle.profile.get("blocs", {}), candidates_payload, valid_votes),
        "projection": None,
        "official_declaration": official,
        "archive": archive_info,
        "wards": ward_rows,
        "streams": stream_payloads,
        "anomaly_feed": [],
        "corrections": [],
    }
    _write_json(bundle.public_path, payload)
    return payload


def _build_blocs(bloc_map: dict[str, list[str]], candidates: list[dict[str, Any]], valid_votes: int | None) -> dict[str, Any]:
    by_id = {str(c["id"]): c.get("votes") for c in candidates}
    output: dict[str, Any] = {}
    for bloc, ids in bloc_map.items():
        values = [by_id.get(cid) for cid in ids]
        votes = sum(int(value) for value in values if value is not None) if all(value is not None for value in values) else None
        output[bloc] = {"votes": votes, "share": votes / valid_votes if votes is not None and valid_votes else None}
    output["note"] = "Historical arithmetic aggregation only. It does not imply transferability between parties."
    return output


def _match_form(bundle: HistoricalBundle, source_label: str, source_url: str) -> dict[str, Any] | None:
    marker = f"{source_label} {source_url}"
    digits = re.sub(r"\D", "", marker)
    exact = [row for row in bundle.streams if str(row["polling_station_code"]) in digits]
    if len(exact) == 1:
        return exact[0]
    norm_marker = _norm(marker)
    candidates = [row for row in bundle.streams if _norm(row["station_name"]) in norm_marker]
    if len(candidates) == 1:
        return candidates[0]
    stream_matches = re.findall(r"(?:STREAM|STRM|S)\s*0?(\d{1,2})", marker.upper())
    if stream_matches and candidates:
        stream_no = int(stream_matches[-1])
        narrowed = [row for row in candidates if int(row["stream_no"]) == stream_no]
        if len(narrowed) == 1:
            return narrowed[0]
    return None


def _safe_extract_zip(bundle: HistoricalBundle, data: bytes, digest: str) -> list[str]:
    """Extract supported form files from a portal ZIP without allowing path traversal."""
    target_root = bundle.election_dir / "documents" / "portal" / digest[:16]
    target_root.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            safe_name = Path(member.filename).name
            if not safe_name or Path(safe_name).suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
                continue
            output = target_root / safe_name
            if not output.exists():
                output.write_bytes(archive.read(member))
            extracted.append(str(output.relative_to(bundle.root)).replace("\\", "/"))
    return extracted


def _archive_download(
    bundle: HistoricalBundle,
    form: Any,
    response: Any,
    reference: dict[str, Any] | None,
    existing: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    body = response.body or b""
    digest = hashlib.sha256(body).hexdigest()
    extension = extension_from_response(response.url, response.headers)
    previous_sha = (existing or {}).get("sha256")
    version = int((existing or {}).get("version", 0)) + (0 if previous_sha == digest else 1)
    version = max(version, 1)
    identity = str(reference["polling_station_code"]) if reference else "unmatched"
    relative = (
        Path("elections")
        / bundle.election_id
        / "forms"
        / identity
        / f"v{version}_{digest[:12]}.{extension}"
    )
    public_path = bundle.root / "data" / "public" / relative
    public_path.parent.mkdir(parents=True, exist_ok=True)
    if not public_path.exists():
        public_path.write_bytes(body)
    extracted_files: list[str] = []
    if extension == "zip":
        extracted_files = _safe_extract_zip(bundle, body, digest)
    changed = previous_sha != digest
    versions = list((existing or {}).get("versions", []))
    if not any(item.get("sha256") == digest for item in versions):
        versions.append(
            {
                "version": version,
                "sha256": digest,
                "archive_path": str(public_path.relative_to(bundle.root)).replace("\\", "/"),
                "public_url": f"../data/public/{relative.as_posix()}",
                "downloaded_at": utc_now_iso(),
            }
        )
    entry: dict[str, Any] = {
        "stream_key": reference.get("stream_key") if reference else None,
        "polling_station_code": reference.get("polling_station_code") if reference else None,
        "source_url": form.source_url,
        "source_label": form.source_label,
        "form_type": form.form_type,
        "discovered_at": (existing or {}).get("discovered_at") or utc_now_iso(),
        "checked_at": utc_now_iso(),
        "sha256": digest,
        "version": version,
        "archive_path": str(public_path.relative_to(bundle.root)).replace("\\", "/"),
        "public_url": f"../data/public/{relative.as_posix()}",
        "downloaded_at": utc_now_iso(),
        "content_type": response.headers.get("content-type"),
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "versions": versions,
        "extracted_files": extracted_files,
    }
    return entry, changed


def _is_constituency_bundle(form: Any) -> bool:
    marker = f"{getattr(form, 'source_label', '')} {getattr(form, 'source_url', '')}".lower()
    return any(token in marker for token in ("download-all", "download all", "bulk download", ".zip"))


def _bundle_member_count(entry: dict[str, Any]) -> int:
    return sum(
        1
        for name in entry.get("extracted_files", [])
        if Path(str(name)).suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
    )


def _zip_supported_member_count(data: bytes) -> int:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return sum(
                1
                for member in archive.infolist()
                if not member.is_dir()
                and Path(member.filename).suffix.lower()
                in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
            )
    except zipfile.BadZipFile:
        return 0


def run_historical_archive(bundle: HistoricalBundle, *, user_agent: str, download: bool = True) -> dict[str, Any]:
    portal = bundle.profile["portal"]
    client = PortalClient(
        portal["index_url"],
        portal["constituency"],
        user_agent,
        constituency_code=bundle.profile["election"]["code"],
        detail_url=portal.get("detail_url"),
        county=bundle.profile.get("election", {}).get("county"),
    )
    manifest = load_manifest(bundle)
    index_meta = manifest.get("index", {})
    try:
        index = client.conditional_get(
            portal["index_url"],
            etag=index_meta.get("etag"),
            last_modified=index_meta.get("last_modified"),
        )
        if index.status_code == 304:
            return {
                "election_id": bundle.election_id,
                "status": "NOT_MODIFIED",
                "changed": False,
                "discovered": int(manifest.get("discovered_count", 0)),
                "matched": int(manifest.get("matched_count", 0)),
                "downloaded": int(manifest.get("downloaded_count", 0)),
                "new_downloads": 0,
                "changed_downloads": 0,
                "unmatched": len(manifest.get("unmatched", [])),
            }
        if index.status_code != 200 or not index.body:
            raise RuntimeError(f"portal returned HTTP {index.status_code}")
        previous_index = dict(manifest.get("index", {}))
        next_index = {
            "etag": index.headers.get("etag"),
            "last_modified": index.headers.get("last-modified"),
        }
        portal_reported, portal_expected = client.reported_counts(index.body)
        discovered = client.discover(index.body, index.url)
        discovered_35a = [form for form in discovered if form.form_type == "35A"]
        bundle_links = [form for form in discovered_35a if _is_constituency_bundle(form)]
        # The IEBC constituency view may expose either one link per form or a
        # constituency-scoped Download All ZIP. One verified bundle is therefore
        # a valid discovery result, but its extracted member count is checked after
        # download before the run is accepted.
        if portal_reported and len(discovered_35a) < portal_reported and not bundle_links:
            debug_path = bundle.election_dir / "portal_debug" / "index_latest.html"
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_bytes(index.body)
            raise RuntimeError(
                "portal discovery incomplete: "
                f"the IEBC index reports {portal_reported} Form 35As for {portal['constituency']}, "
                f"but only {len(discovered_35a)} download links were found and no constituency bundle was discovered. "
                f"Saved the index snapshot to {debug_path.relative_to(bundle.root)}."
            )
        previous_urls = set(manifest.get("forms", {}))
        unmatched: list[dict[str, str]] = []
        new_downloads = 0
        changed_downloads = 0
        for form in discovered:
            reference = _match_form(bundle, form.source_label, form.source_url)
            if reference is None and form.form_type == "35A":
                unmatched.append({"source_url": form.source_url, "source_label": form.source_label})
            existing = manifest.setdefault("forms", {}).get(form.source_url)
            if not download:
                manifest["forms"][form.source_url] = {
                    **(existing or {}),
                    "stream_key": reference.get("stream_key") if reference else None,
                    "polling_station_code": reference.get("polling_station_code") if reference else None,
                    "source_url": form.source_url,
                    "source_label": form.source_label,
                    "form_type": form.form_type,
                    "discovered_at": (existing or {}).get("discovered_at") or utc_now_iso(),
                }
                continue
            archive_path = (existing or {}).get("archive_path")
            archive_exists = bool(archive_path and (bundle.root / archive_path).exists())
            # Known immutable files are not downloaded every five minutes. When the
            # index changes, new URLs are fetched; amended URLs can be rechecked by
            # setting recheck_existing=true in the election profile.
            if existing and archive_exists and not bool(portal.get("recheck_existing", False)):
                continue
            response = client.conditional_get(
                form.source_url,
                etag=(existing or {}).get("etag"),
                last_modified=(existing or {}).get("last_modified"),
            )
            if response.status_code == 304:
                continue
            if response.status_code != 200 or response.body is None:
                manifest["forms"][form.source_url] = {
                    **(existing or {}),
                    "source_url": form.source_url,
                    "source_label": form.source_label,
                    "download_error": f"HTTP {response.status_code}",
                    "checked_at": utc_now_iso(),
                }
                continue
            if _is_constituency_bundle(form) and portal_reported:
                extension = extension_from_response(response.url, response.headers)
                member_count = _zip_supported_member_count(response.body) if extension == "zip" else 0
                if member_count != portal_reported:
                    debug_path = bundle.election_dir / "portal_debug" / "bundle_response_latest.bin"
                    debug_path.parent.mkdir(parents=True, exist_ok=True)
                    debug_path.write_bytes(response.body[:2_000_000])
                    raise RuntimeError(
                        "constituency Download All response rejected: "
                        f"expected exactly {portal_reported} Form 35A files for {portal['constituency']}, "
                        f"but received {member_count} supported files (content type "
                        f"{response.headers.get('content-type', 'unknown')}). "
                        f"Saved a bounded response sample to {debug_path.relative_to(bundle.root)}."
                    )
            entry, changed = _archive_download(bundle, form, response, reference, existing)
            manifest["forms"][form.source_url] = entry
            if existing is None:
                new_downloads += 1
            elif changed:
                changed_downloads += 1
        if download and portal_reported and bundle_links:
            bundle_entries = [
                manifest.get("forms", {}).get(form.source_url, {})
                for form in bundle_links
            ]
            bundle_members = sum(_bundle_member_count(entry) for entry in bundle_entries)
            if bundle_members != portal_reported:
                debug_path = bundle.election_dir / "portal_debug" / "index_latest.html"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_bytes(index.body)
                raise RuntimeError(
                    "constituency bundle incomplete: "
                    f"the IEBC index reports {portal_reported} Form 35As for {portal['constituency']}, "
                    f"but the downloaded bundle yielded {bundle_members} supported form files instead of exactly {portal_reported}. "
                    f"Saved the index snapshot to {debug_path.relative_to(bundle.root)}."
                )

        matched_count = len(
            {
                item.get("stream_key")
                for item in manifest.get("forms", {}).values()
                if item.get("stream_key") and item.get("form_type", "35A") == "35A"
            }
        )
        downloaded_count = sum(
            max(1, _bundle_member_count(item))
            for item in manifest.get("forms", {}).values()
            if item.get("sha256")
        )
        bundle_member_total = sum(
            _bundle_member_count(manifest.get("forms", {}).get(form.source_url, {}))
            for form in bundle_links
        )
        effective_discovered_count = max(len(discovered), bundle_member_total)
        discovered_urls = {form.source_url for form in discovered}
        metadata_changed = (
            previous_index != next_index
            or discovered_urls - previous_urls
            or int(manifest.get("discovered_count", -1)) != effective_discovered_count
            or int(manifest.get("matched_count", -1)) != matched_count
            or int(manifest.get("downloaded_count", -1)) != downloaded_count
            or manifest.get("portal_reported") != portal_reported
            or manifest.get("portal_expected") != portal_expected
            or manifest.get("unmatched", []) != unmatched
        )
        changed = bool(new_downloads or changed_downloads or metadata_changed or not bundle.manifest_path.exists())
        if changed:
            manifest.update(
                {
                    "index": next_index,
                    "last_portal_ok": utc_now_iso(),
                    "discovered_count": effective_discovered_count,
                    "matched_count": matched_count,
                    "downloaded_count": downloaded_count,
                    "portal_reported": portal_reported,
                    "portal_expected": portal_expected,
                    "unmatched": unmatched,
                }
            )
            _write_json(bundle.manifest_path, manifest)
        return {
            "election_id": bundle.election_id,
            "status": "UPDATED" if changed else "NO_CHANGE",
            "changed": changed,
            "discovered": effective_discovered_count,
            "matched": matched_count,
            "downloaded": downloaded_count,
            "new_downloads": new_downloads,
            "changed_downloads": changed_downloads,
            "unmatched": len(unmatched),
            "portal_reported": portal_reported,
            "portal_expected": portal_expected,
        }
    finally:
        client.close()


def build_catalog(root: Path) -> dict[str, Any]:
    elections_dir = root / "data" / "elections"
    entries: list[dict[str, Any]] = []
    for profile_path in sorted(elections_dir.glob("*/election.json")):
        profile = _read_json(profile_path)
        election = profile["election"]
        entries.append({
            "id": profile["id"],
            "label": f"{election['constituency'].title()} · {datetime.fromisoformat(election['date']).strftime('%d %b %Y')}",
            "mode": profile.get("mode", "ARCHIVE"),
            "constituency": election["constituency"],
            "date": election["date"],
            "data_url": f"../data/public/elections/{profile['id']}.json",
        })
    entries.sort(key=lambda row: row["date"], reverse=True)
    catalog = {"schema": "kenya.election.catalog.v1", "default": entries[0]["id"] if entries else None, "elections": entries}
    _write_json(root / "data" / "public" / "elections" / "catalog.json", catalog)
    return catalog
