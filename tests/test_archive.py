from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from olkalou_engine.archive import (
    build_archive_payload,
    build_catalog,
    import_verified_results,
    load_historical_bundle,
    _ocr_prefill,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _clear_generated_runtime_state(target: Path) -> None:
    """Keep tests independent from committed portal/OCR snapshots.

    The repository intentionally stores generated historical evidence. Tests that
    create their own OCR/manifest fixtures must start from the immutable election
    profile and stream register, not from whichever sync snapshot is on main.
    """
    for name in ("forms_manifest.json", "sync_status.json", "verified_results.json"):
        (target / name).unlink(missing_ok=True)
    for relative in (
        "ocr/extractions",
        "forms",
        "portal_debug",
    ):
        shutil.rmtree(target / relative, ignore_errors=True)
    for relative in (
        "ocr/document_inventory.json",
        "ocr/form35b_review.json",
        "ocr/review_queue.csv",
        "ocr/summary.json",
    ):
        (target / relative).unlink(missing_ok=True)


def copy_banissa(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = REPO_ROOT / "data" / "elections" / "banissa-2025"
    target = root / "data" / "elections" / "banissa-2025"
    target.parent.mkdir(parents=True)
    shutil.copytree(source, target)
    _clear_generated_runtime_state(target)
    return root


def _write_extraction(root: Path, election_id: str, stream_key: str, fields: dict, *,
                       confidence: float = 0.8, route: str = "QUARANTINE", form_type: str = "35A"):
    extraction_dir = root / "data" / "elections" / election_id / "ocr" / "extractions"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "kenya.election.ocr-extraction.v1", "election_id": election_id,
        "page_id": f"test-{stream_key}", "stream_key": stream_key, "form_type": form_type,
        "confidence": confidence, "route": route,
        "checks": {"V01": "FAIL", "V07": "PASS"},
        "parsed": {"fields": fields},
    }
    (extraction_dir / f"test-{stream_key.replace('/', '_')}.json").write_text(json.dumps(payload))


def test_banissa_reference_frame_is_complete() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    assert len(bundle.streams) == 81
    assert sum(int(row["registered"]) for row in bundle.streams) == 32_703
    assert [candidate["id"] for candidate in bundle.candidates] == ["UDA", "UPA"]


def test_archive_payload_withholds_stream_replay_until_forms_are_transcribed(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)

    assert payload["schema"] == "kenya.election.archive.v1"
    assert payload["coverage"]["streams_total"] == 81
    assert payload["coverage"]["published"] == 0
    assert payload["archive"]["replay_available"] is False
    assert payload["archive"]["tally_source"] == "OFFICIAL_DECLARATION"
    assert payload["totals"]["valid_votes"] == 11_671


def test_imported_stream_must_pass_statutory_checks(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    reference = bundle.streams[0]
    csv_path = root / "one-stream.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "stream_key", "reported_at", "form_url", "verification",
                "registered_form", "UDA", "UPA", "rejected", "po_total_valid",
                "total_cast_form", "reviewer_a", "reviewer_b", "notes",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "stream_key": reference["stream_key"],
            "reported_at": "2025-11-27T19:00:00Z",
            "form_url": "https://example.test/form-35a.pdf",
            "verification": "HUMAN",
            "registered_form": reference["registered"],
            "UDA": 100,
            "UPA": 20,
            "rejected": 2,
            "po_total_valid": 120,
            "total_cast_form": 122,
            "reviewer_a": "A",
            "reviewer_b": "B",
            "notes": "fixture",
        })

    imported = import_verified_results(bundle, csv_path)
    assert len(imported["results"]) == 1
    assert set(imported["results"][0]["checks"].values()) == {"PASS"}

    payload = build_archive_payload(bundle)
    assert payload["coverage"]["published"] == 1
    assert payload["archive"]["replay_available"] is False
    assert payload["streams"][0]["state"] == "PUBLISHED"


def test_import_rejects_register_mismatch(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    reference = bundle.streams[0]
    csv_path = root / "bad.csv"
    csv_path.write_text(
        "stream_key,reported_at,form_url,verification,registered_form,UDA,UPA,rejected,po_total_valid,total_cast_form\n"
        f"{reference['stream_key']},2025-11-27T19:00:00Z,,HUMAN,1,1,0,0,1,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="V07"):
        import_verified_results(bundle, csv_path)


def test_catalog_points_to_generated_archive_payload(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    build_archive_payload(bundle)
    catalog = build_catalog(root)
    assert catalog["default"] == "banissa-2025"
    assert catalog["elections"][0]["data_url"].endswith("banissa-2025.json")
    stored = json.loads((root / "data/public/elections/catalog.json").read_text(encoding="utf-8"))
    assert stored == catalog


def test_ocr_prefill_extracts_candidate_votes_and_controls() -> None:
    record = {
        "parsed": {"fields": {
            "candidate_UDA": {"value": 245, "confidence": 0.8},
            "candidate_UPA": {"value": 12, "confidence": 0.75},
            "registered": {"value": 484, "confidence": 0.9},
            "rejected": {"value": 3, "confidence": 0.6},
            "total_valid": {"value": 257, "confidence": 0.7},
            "total_cast": {"value": 260, "confidence": 0.7},
        }},
    }
    prefill = _ocr_prefill(record, ["UDA", "UPA"])
    assert prefill == {
        "votes": {"UDA": 245, "UPA": 12},
        "registered": 484, "rejected": 3, "total_valid": 257, "total_cast": 260,
    }


def test_ocr_prefill_omits_candidates_the_parser_could_not_read() -> None:
    record = {"parsed": {"fields": {"candidate_UDA": {"value": 245, "confidence": 0.8}}}}
    prefill = _ocr_prefill(record, ["UDA", "UPA"])
    assert prefill["votes"] == {"UDA": 245}  # UPA simply absent, not zero-filled


def test_ocr_prefill_returns_none_for_no_record_or_empty_extraction() -> None:
    assert _ocr_prefill(None, ["UDA", "UPA"]) is None
    assert _ocr_prefill({"parsed": {"fields": {}}}, ["UDA", "UPA"]) is None


def test_stream_payload_surfaces_ocr_prefill_without_touching_verified_votes(tmp_path: Path) -> None:
    """The exact safety property this feature depends on: OCR prefill is
    additive, source-linked evidence under stream.ocr.prefill -- it must
    never appear in, or alter, stream.votes (which stays reserved for
    statutorily-checked, human-verified figures)."""
    root = copy_banissa(tmp_path)
    stream_key = "040-0196-001-01"
    _write_extraction(root, "banissa-2025", stream_key, {
        "candidate_UDA": {"value": 245, "confidence": 0.8},
        "candidate_UPA": {"value": 12, "confidence": 0.75},
        "registered": {"value": 484, "confidence": 0.9},
    })
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)

    stream = next(s for s in payload["streams"] if s["stream_key"] == stream_key)
    assert stream["votes"] == {}  # untouched -- still not a verified result
    assert stream["ocr"]["prefill"]["votes"] == {"UDA": 245, "UPA": 12}
    assert stream["ocr"]["prefill"]["registered"] == 484
    assert stream["ocr"]["route"] == "QUARANTINE"
    assert stream["ocr"]["checks"] == {"V01": "FAIL", "V07": "PASS"}
    # And the constituency-level totals must be completely unaffected:
    assert payload["totals"]["valid_votes"] == 11_671  # still the certified Gazette figure


def test_stream_with_no_ocr_record_has_no_ocr_key_at_all(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)
    stream = payload["streams"][0]
    assert stream["ocr"] is None


def test_readiness_stats_reconcile_with_real_banissa_screenshot_shape(tmp_path: Path) -> None:
    """Regression check tied to the real dashboard review (14 Jul 2026):
    forms_archived must never be silently inflated to look like
    portal_downloaded -- that inflation lived only in the frontend's old
    Math.max() call (now removed), but pin the backend's honest number here
    too so nothing reintroduces it on this side."""
    root = copy_banissa(tmp_path)
    for i in range(3):
        _write_extraction(root, "banissa-2025", f"040-0196-00{i+1}-01", {
            "candidate_UDA": {"value": 10 + i, "confidence": 0.8},
        })
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)
    assert payload["archive"]["forms_archived"] == 3
    assert payload["archive"]["forms_expected"] == 81
    # Honest: nowhere near the expected total just because SOME forms exist.
    assert payload["archive"]["forms_archived"] < payload["archive"]["forms_expected"]
