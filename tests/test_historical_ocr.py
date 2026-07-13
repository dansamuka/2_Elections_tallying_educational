from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from olkalou_engine.archive import build_archive_payload, load_historical_bundle
from olkalou_engine.config import Settings
from olkalou_engine.historical_ocr import (
    FORM_35A,
    FORM_35B,
    classify_form,
    inventory_documents,
    match_stream,
    parse_form35a,
    parse_form35b,
    run_historical_ocr,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_banissa(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = REPO_ROOT / "data" / "elections" / "banissa-2025"
    target = root / "data" / "elections" / "banissa-2025"
    target.parent.mkdir(parents=True)
    shutil.copytree(source, target)
    return root


def sample_35a_text(bundle, stream) -> str:
    return f"""
    ELECTIONS ACT FORM 35A
    POLLING STATION: {stream['station_name']} STREAM {stream['stream_no']}
    POLLING STATION CODE {stream['polling_station_code']}
    NUMBER OF REGISTERED VOTERS {stream['registered']}
    Hassan Ahmed Maalim UDA 100
    Mohamed Nurdin Maalim UPA 20
    TOTAL VALID VOTES 120
    REJECTED BALLOTS 2
    TOTAL VOTES CAST 122
    """


def test_form_classification_and_parsing() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    stream = bundle.streams[0]
    text = sample_35a_text(bundle, stream)
    assert classify_form(text, "scan.pdf") == FORM_35A
    matched, method = match_stream(bundle, text, "scan.pdf")
    assert matched is not None
    assert matched["stream_key"] == stream["stream_key"]
    assert method in {"POLLING_CODE", "POLLING_CODE_AND_STREAM", "STATION_NAME_AND_STREAM"}
    parsed = parse_form35a(text, bundle.candidates)
    assert parsed["fields"]["candidate_UDA"]["value"] == 100
    assert parsed["fields"]["candidate_UPA"]["value"] == 20
    assert parsed["fields"]["total_valid"]["value"] == 120
    assert parsed["fields"]["registered"]["value"] == stream["registered"]


def test_form35b_parser() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    text = """
    FORM 35B DECLARATION OF RESULT AT CONSTITUENCY TALLYING CENTRE
    Hassan Ahmed Maalim UDA 10431
    Mohamed Nurdin Maalim UPA 1240
    TOTAL VALID VOTES 11671
    REJECTED BALLOTS 13
    TOTAL VOTES CAST 11684
    """
    assert classify_form(text, "banissa-form35b.pdf") == FORM_35B
    parsed = parse_form35b(text, bundle.candidates)
    assert parsed["candidate_totals"] == {"UDA": 10431, "UPA": 1240}
    assert parsed["valid_votes"] == 11671
    assert parsed["total_cast"] == 11684


def test_inventory_deduplicates_identical_uploads(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    documents = bundle.election_dir / "documents"
    documents.mkdir(exist_ok=True)
    (documents / "a.pdf").write_bytes(b"same")
    (documents / "copy.pdf").write_bytes(b"same")
    monkeypatch.setattr("olkalou_engine.historical_ocr._page_count", lambda path: 1)
    inventory = inventory_documents(bundle)
    assert inventory["documents_total"] == 1
    assert inventory["duplicates_collapsed"] == 1
    assert len(inventory["documents"][0]["aliases"]) == 2


def test_historical_ocr_creates_review_queue_without_publishing(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    stream = bundle.streams[0]
    documents = bundle.election_dir / "documents"
    documents.mkdir(exist_ok=True)
    source = documents / f"FORM35A_{stream['polling_station_code']}_STREAM1.pdf"
    source.write_bytes(b"fixture")
    monkeypatch.setattr("olkalou_engine.historical_ocr._page_count", lambda path: 1)
    monkeypatch.setattr(
        "olkalou_engine.historical_ocr._embedded_text",
        lambda path, page_no: sample_35a_text(bundle, stream),
    )
    settings = Settings(ENGINE_ROOT=root)
    summary = run_historical_ocr(bundle, settings, engine_mode="embedded")
    assert summary["documents_total"] == 1
    assert summary["form35a_detected"] == 1
    assert summary["streams_matched"] == 1
    assert summary["review_rows"] == 1
    assert summary["auto_publication"] is False

    review_path = bundle.election_dir / "ocr" / "review_queue.csv"
    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["stream_key"] == stream["stream_key"]
    assert rows[0]["UDA"] == "100"
    assert rows[0]["UPA"] == "20"
    assert rows[0]["ocr_route"] == "READY_FOR_DOUBLE_REVIEW"

    assert not bundle.verified_results_path.exists()
    payload = build_archive_payload(bundle)
    assert payload["coverage"]["published"] == 0
    assert payload["archive"]["ocr"]["review_rows"] == 1
    assert payload["pipeline_health"]["extractor"] == "OCR_REVIEW_READY"


def test_empty_document_set_is_reported_honestly(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    settings = Settings(ENGINE_ROOT=root)
    summary = run_historical_ocr(bundle, settings, engine_mode="embedded")
    assert summary["documents_total"] == 0
    assert summary["pages_processed"] == 0
    stored = json.loads((bundle.election_dir / "ocr" / "summary.json").read_text())
    assert stored["auto_publication"] is False
