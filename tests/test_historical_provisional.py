from __future__ import annotations

import json
import shutil
from pathlib import Path

from olkalou_engine.archive import load_historical_bundle
from olkalou_engine.historical_provisional import build_historical_provisional

REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_banissa(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = REPO_ROOT / "data" / "elections" / "banissa-2025"
    target = root / "data" / "elections" / "banissa-2025"
    target.parent.mkdir(parents=True)
    shutil.copytree(source, target)
    return root


def _write_extraction(root: Path, election_id: str, stream_key: str, votes: dict, *,
                       confidence: float = 0.8, route: str = "READY_FOR_DOUBLE_REVIEW"):
    extraction_dir = root / "data" / "elections" / election_id / "ocr" / "extractions"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    fields = {f"candidate_{cid}": {"value": v, "confidence": confidence} for cid, v in votes.items()}
    payload = {
        "schema": "kenya.election.ocr-extraction.v1",
        "election_id": election_id,
        "page_id": f"test-{stream_key}",
        "stream_key": stream_key,
        "form_type": "35A",
        "confidence": confidence,
        "route": route,
        "parsed": {"fields": fields},
    }
    (extraction_dir / f"test-{stream_key.replace('/', '_')}.json").write_text(json.dumps(payload))


def test_no_extractions_yet_gives_zero_contributing(tmp_path: Path):
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    result = build_historical_provisional(bundle)
    assert result["streams_contributing"] == 0
    assert all(c["votes"] == 0 for c in result["candidates"])
    assert result["PROVISIONAL_UNVERIFIED"] is True


def test_ocr_only_extraction_contributes_even_when_quarantined(tmp_path: Path):
    """The whole point, same as the live-election version: a QUARANTINED
    (statutory checks failed / not reviewed) OCR extraction still counts
    here -- that's what makes it provisional rather than verified."""
    root = copy_banissa(tmp_path)
    stream_key = "040-0196-001-01"
    _write_extraction(root, "banissa-2025", stream_key, {"UDA": 300, "UPA": 150}, route="QUARANTINE")
    bundle = load_historical_bundle(root, "banissa-2025")
    result = build_historical_provisional(bundle)
    assert result["streams_contributing"] == 1
    uda = next(c for c in result["candidates"] if c["id"] == "UDA")
    assert uda["votes"] == 300
    assert result["source_breakdown"] == {"VERIFIED": 0, "OCR_ONLY": 1}


def test_verified_result_takes_precedence_over_ocr_for_same_stream(tmp_path: Path):
    import csv

    root = copy_banissa(tmp_path)
    stream_key = "040-0196-001-01"
    # OCR says one thing (e.g. a misread)...
    _write_extraction(root, "banissa-2025", stream_key, {"UDA": 999, "UPA": 999})
    # ...but a human-verified, statutorily-valid CSV import says another.
    bundle = load_historical_bundle(root, "banissa-2025")
    registered = int(next(s["registered"] for s in bundle.streams if s["stream_key"] == stream_key))
    csv_path = root / "verified.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "stream_key", "reported_at", "form_url", "verification", "registered_form",
            "UDA", "UPA", "rejected", "po_total_valid", "total_cast_form",
            "reviewer_a", "reviewer_b", "notes",
        ])
        writer.writeheader()
        writer.writerow({
            "stream_key": stream_key, "reported_at": "2025-11-27T18:00:00Z", "form_url": "",
            "verification": "HUMAN", "registered_form": registered, "UDA": 200, "UPA": 50,
            "rejected": 2, "po_total_valid": 250, "total_cast_form": 252,
            "reviewer_a": "a", "reviewer_b": "b", "notes": "",
        })
    from olkalou_engine.archive import import_verified_results
    import_verified_results(bundle, csv_path)

    result = build_historical_provisional(bundle)
    assert result["streams_contributing"] == 1
    uda = next(c for c in result["candidates"] if c["id"] == "UDA")
    assert uda["votes"] == 200  # the verified figure, NOT the OCR 999
    assert result["source_breakdown"] == {"VERIFIED": 1, "OCR_ONLY": 0}


def test_official_declaration_shown_for_reference_only(tmp_path: Path):
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    result = build_historical_provisional(bundle)
    assert result["official_declaration_for_reference"]["candidate_totals"] == {"UDA": 10431, "UPA": 1240}
    assert "not derived from the sum above" in result["official_declaration_for_reference"]["note"]


def test_warning_always_present():
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    result = build_historical_provisional(bundle)
    assert "NOT A CERTIFIED RESULT" in result["warning"]
    assert result["schema"] == "kenya.election.historical-provisional.v1"


def test_archive_payload_never_gains_provisional_data(tmp_path: Path):
    """Regression lock, same discipline as the live-election test: the
    public archive payload must never fold OCR-only figures into anything
    that looks like a real total."""
    from olkalou_engine.archive import build_archive_payload

    root = copy_banissa(tmp_path)
    stream_key = "040-0196-001-01"
    _write_extraction(root, "banissa-2025", stream_key, {"UDA": 777, "UPA": 1})
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)

    assert "provisional" not in payload
    assert "PROVISIONAL_UNVERIFIED" not in payload
    # OCR-only figures must not have leaked into the officially-shown totals:
    assert payload["totals"]["valid_votes"] == 11_671  # the certified Gazette figure, untouched
    stream_row = next(s for s in payload["streams"] if s["stream_key"] == stream_key)
    assert stream_row["votes"] == {}  # not 777
