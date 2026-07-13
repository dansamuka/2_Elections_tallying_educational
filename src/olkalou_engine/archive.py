from __future__ import annotations

import csv
import hashlib
import json
import re
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
    if len(streams) != expected:
        raise ValueError(f"expected {expected} streams, found {len(streams)}")
    keys = [str(row["stream_key"]) for row in streams]
    codes = [str(row["polling_station_code"]) for row in streams]
    if len(set(keys)) != len(keys):
        raise ValueError("historical stream keys must be unique")
    if len(set(codes)) != len(codes):
        raise ValueError("historical polling-station codes must be unique")
    actual_total = sum(int(row["registered"]) for row in streams)
    if actual_total != register_total:
        raise ValueError(f"register total mismatch: {actual_total} != {register_total}")
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
            checks = _checks_for_row(row, int(references[stream_key]["registered"]), candidate_ids)
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


def build_archive_payload(bundle: HistoricalBundle) -> dict[str, Any]:
    results = _load_results(bundle)
    manifest_by_stream = _manifest_by_stream(bundle)
    candidate_ids = [str(c["id"]) for c in bundle.candidates]
    official = bundle.profile.get("official_declaration", {})
    ocr_summary = load_ocr_summary(bundle)
    ocr_by_stream = load_ocr_stream_extractions(bundle)
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
                } if ocr_record else None,
                "published_at": None,
            }
        stream_payloads.append(payload)

    stream_results_complete = len(results) == len(bundle.streams)
    tally_source = "FORM_35A_SUM" if stream_results_complete else "OFFICIAL_DECLARATION"
    if not stream_results_complete:
        official_totals = official.get("candidate_totals", {})
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
        "forms_archived": len(manifest_by_stream),
        "stream_results_transcribed": len(results),
        "stream_results_complete": stream_results_complete,
        "tally_source": tally_source,
        "replay_available": stream_results_complete and len(replay_events) == len(results),
        "replay_events": replay_events if stream_results_complete else [],
        "methodology_note": bundle.profile.get("methodology", {}).get("note"),
        "ocr": ocr_summary,
    }
    coverage = {
        "streams_total": len(bundle.streams),
        "published": len(results),
        "in_review": max(0, len(manifest_by_stream) - len(results)),
        "conflicted": 0,
        "awaiting": max(0, len(bundle.streams) - len(manifest_by_stream)),
        "reference_only": sum(1 for row in stream_payloads if row["state"] == "REFERENCE_ONLY"),
        "archived_untranscribed": sum(1 for row in stream_payloads if row["state"] == "ARCHIVED"),
        "ocr_review": sum(1 for row in stream_payloads if row["state"] == "OCR_REVIEW"),
        "registered_total": int(bundle.profile["register"]["total"]),
        "registered_reported": published_registered,
        "registered_pct": published_registered / int(bundle.profile["register"]["total"]) if published_registered else 0.0,
        "excluded": {"count": 0, "reason": None},
    }
    ward_rows = []
    for ward in sorted({row["ward_name"] for row in bundle.streams}):
        refs = [row for row in bundle.streams if row["ward_name"] == ward]
        pubs = [row for row in stream_payloads if row["ward"] == ward and row["state"] == "PUBLISHED"]
        ward_rows.append({
            "code": refs[0]["ward_code"],
            "name": ward,
            "streams_total": len(refs),
            "published": len(pubs),
            "registered": sum(int(row["registered"]) for row in refs),
            "registered_reported": sum(int(row["registered"]) for row in pubs),
            "turnout": None,
            "candidates": {cid: sum(int(row["votes"].get(cid, 0)) for row in pubs) for cid in candidate_ids},
        })

    payload = {
        "schema": "kenya.election.archive.v1",
        "seq": int(datetime.now(timezone.utc).timestamp() * 1000),
        "generated_at": utc_now_iso(),
        "mode": "ARCHIVE",
        "election_id": bundle.election_id,
        "election": bundle.profile["election"],
        "status": "FINAL",
        "reference": {
            "complete": True,
            "errors": [],
            "register_source": bundle.profile["register"]["source"],
            "register_source_url": bundle.profile["register"].get("source_url"),
            "candidate_source": "Kenya Gazette Notice No. 15731, 29 October 2025",
        },
        "pipeline_health": {
            "watcher": "ARCHIVE",
            "extractor": (
                "OCR_REVIEW_READY" if ocr_summary.get("pages_processed", 0) else "MANUAL_REVIEW"
            ),
            "last_portal_ok": None,
            "worker_id": "archive",
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


def run_historical_archive(bundle: HistoricalBundle, *, user_agent: str, download: bool = True) -> dict[str, Any]:
    portal = bundle.profile["portal"]
    client = PortalClient(
        portal["index_url"],
        portal["constituency"],
        user_agent,
        constituency_code=bundle.profile["election"]["code"],
    )
    try:
        index = client.get_with_backoff(portal["index_url"])
        if index.status_code != 200 or not index.body:
            raise RuntimeError(f"portal returned HTTP {index.status_code}")
        discovered = [form for form in client.discover(index.body, index.url) if form.form_type == "35A"]
        manifest = load_manifest(bundle)
        unmatched: list[dict[str, str]] = []
        for form in discovered:
            reference = _match_form(bundle, form.source_label, form.source_url)
            if reference is None:
                unmatched.append({"source_url": form.source_url, "source_label": form.source_label})
                continue
            entry: dict[str, Any] = {
                "stream_key": reference["stream_key"],
                "polling_station_code": reference["polling_station_code"],
                "source_url": form.source_url,
                "source_label": form.source_label,
                "discovered_at": utc_now_iso(),
            }
            if download:
                response = client.get_with_backoff(form.source_url)
                if response.status_code != 200 or response.body is None:
                    entry["download_error"] = f"HTTP {response.status_code}"
                else:
                    digest = hashlib.sha256(response.body).hexdigest()
                    extension = extension_from_response(response.url, response.headers)
                    relative = Path("elections") / bundle.election_id / "forms" / f"{reference['polling_station_code']}_{digest[:12]}.{extension}"
                    public_path = bundle.root / "data" / "public" / relative
                    public_path.parent.mkdir(parents=True, exist_ok=True)
                    if not public_path.exists():
                        public_path.write_bytes(response.body)
                    entry.update({
                        "sha256": digest,
                        "archive_path": str(public_path.relative_to(bundle.root)),
                        "public_url": f"../data/public/{relative.as_posix()}",
                        "downloaded_at": utc_now_iso(),
                    })
            manifest["forms"][form.source_url] = entry
        manifest.update({
            "last_portal_ok": utc_now_iso(),
            "discovered_count": len(discovered),
            "matched_count": sum(1 for item in manifest["forms"].values() if item.get("stream_key")),
            "unmatched": unmatched,
        })
        _write_json(bundle.manifest_path, manifest)
        payload = build_archive_payload(bundle)
        return {
            "election_id": bundle.election_id,
            "discovered": len(discovered),
            "matched": manifest["matched_count"],
            "unmatched": len(unmatched),
            "public_path": str(bundle.public_path),
            "coverage": payload["coverage"],
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
