from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from olkalou_engine.archive import _match_form, build_archive_payload, load_historical_bundle
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


def real_35a_text(station_name: str, station_no: int, total_streams: int, polling_code: str) -> str:
    """Transcribed as closely as possible from a real scanned Banissa Form
    35A (see ARCHIVE_DASHBOARD_AND_REVIEW_WORKBENCH_NOTES.md /
    OCR_AND_MATCHING_ACCURACY_NOTES.md) -- deliberately NOT the idealized
    phrasing sample_35a_text() above uses. The real form says "POLLING
    STATION X of Y", never "Stream N", and "Total Number of Rejected Ballot
    Papers", never "Rejected Ballots" -- both label mismatches were real
    bugs, invisible to a test using idealized text.
    """
    return f"""
    MEMBER OF THE NATIONAL ASSEMBLY BY-ELECTION RESULTS AT THE POLLING STATION
    Name of Polling Station {station_name.upper()} POLLING STATION {station_no} of {total_streams}
    Ward BANISSA Code 0196
    Constituency BANISSA Code 040
    County MANDERA Code 009
    Code {polling_code}
    Number of votes cast in favour of each candidate:
    1. HASSAN AHMED MAALIM 137
    2. MOHAMED NURDIN MAALIM 7
    Total number of valid votes cast 144
    Polling Station Counts
    1. Total Number of Registered Voters in the Polling Station 672
    2. Total Number of Rejected Ballot Papers 0
    3. Total Number of Rejection Objected to Ballot Papers 0
    4. Total Number of Disputed Votes 0
    5. Total Number of Valid Votes Cast 144
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


# --- Real-form-text regression tests (13/14 Jul 2026 dashboard review) -----
# The tests above use idealized text ("REJECTED BALLOTS", "STREAM N") that
# happens to match the OLD label patterns -- which is exactly how the real
# mismatch against the actual printed form went unnoticed. These use text
# transcribed from a real scanned Banissa Form 35A instead.

def test_match_stream_reads_the_real_polling_station_x_of_y_phrasing() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    stream = next(s for s in bundle.streams if s["station_name"] == "Ogondicho Primary School" and s["stream_no"] == 2)
    text = real_35a_text(stream["station_name"], 2, 2, stream["polling_station_code"])
    matched, method = match_stream(bundle, text, "scan.pdf")
    assert matched is not None
    assert matched["stream_key"] == stream["stream_key"]
    assert method in {"POLLING_CODE", "POLLING_CODE_AND_STREAM", "STATION_NAME_AND_STREAM"}


def test_match_stream_disambiguates_via_polling_station_phrasing_even_without_a_readable_code() -> None:
    """Same real phrasing, but simulate the code being unreadable (common --
    it's small print) -- matching must still work from the station name +
    "POLLING STATION 1 of 2" alone, which needed the new regex branch."""
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    stream = next(s for s in bundle.streams if s["station_name"] == "Lulis Primary School" and s["stream_no"] == 1)
    text = f"""
    Name of Polling Station {stream['station_name'].upper()} POLLING STATION 1 of 2
    Ward BANISSA
    """
    matched, method = match_stream(bundle, text, "scan.pdf")
    assert matched is not None
    assert matched["stream_key"] == stream["stream_key"]
    assert method == "STATION_NAME_AND_STREAM"


def test_parse_form35a_extracts_rejected_from_the_real_form_phrasing() -> None:
    """The old label list ("REJECTED BALLOTS") never matched the real form
    ("Total Number of Rejected Ballot Papers") -- rejected was silently
    unextractable from every real Banissa form regardless of OCR quality."""
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    stream = bundle.streams[0]
    text = real_35a_text(stream["station_name"], 1, 1, stream["polling_station_code"])
    parsed = parse_form35a(text, bundle.candidates)
    assert parsed["fields"]["rejected"]["value"] == 0
    assert parsed["fields"]["registered"]["value"] == 672
    assert parsed["fields"]["candidate_UDA"]["value"] == 137
    assert parsed["fields"]["candidate_UPA"]["value"] == 7


def test_parse_form35a_derives_total_cast_when_the_form_has_no_explicit_field() -> None:
    """This Form 35A layout has no "total votes cast" line at all -- confirmed
    against a real form. Must derive it from valid + rejected rather than
    leave it permanently blank."""
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    stream = bundle.streams[0]
    text = real_35a_text(stream["station_name"], 1, 1, stream["polling_station_code"])
    parsed = parse_form35a(text, bundle.candidates)
    assert parsed["fields"]["total_cast"]["value"] == 144  # 144 valid + 0 rejected
    assert "derived" in (parsed["evidence"]["total_cast"] or "")
    # Confidence must never exceed either input's own confidence:
    assert parsed["fields"]["total_cast"]["confidence"] <= parsed["fields"]["total_valid"]["confidence"]
    assert parsed["fields"]["total_cast"]["confidence"] <= parsed["fields"]["rejected"]["confidence"]


def test_match_form_disambiguates_iebcs_real_trailing_number_convention() -> None:
    """IEBC's actual portal labels a repeated polling centre as "<NAME> NN"
    with no "Stream"/"S" keyword at all -- e.g. "BANISA PRIMARY SCHOOL 02".
    34 of Banissa's 81 streams share a station name with at least one other
    stream; before this fix, none of them could be disambiguated this way."""
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    target = next(s for s in bundle.streams if s["station_name"] == "Banisa Primary School" and s["stream_no"] == 3)
    matched = _match_form(bundle, "BANISA PRIMARY SCHOOL 03", "https://forms.iebc.or.ke/download?id=4821")
    assert matched is not None
    assert matched["stream_key"] == target["stream_key"]


def test_match_form_never_uses_url_digits_for_disambiguation() -> None:
    """The trailing-number fallback is scoped to source_label only. A
    download URL routinely carries unrelated numeric IDs (page ids,
    timestamps) -- using one of those to pick a stream would silently
    mismatch a form to the wrong stream instead of safely returning
    unmatched."""
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    # Label alone doesn't disambiguate (no trailing number); a stray "07" in
    # the URL must NOT be used to pretend it does.
    matched = _match_form(bundle, "BANISA PRIMARY SCHOOL", "https://forms.iebc.or.ke/download?id=07&p=2")
    assert matched is None


def test_match_form_still_returns_none_when_genuinely_ambiguous() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    matched = _match_form(bundle, "BANISA PRIMARY SCHOOL", "https://forms.iebc.or.ke/download?id=4821")
    assert matched is None


# --- "auto" engine selection fix (13/14 Jul 2026 dashboard review) --------
# FIX: "auto" used to be hardcoded to Tesseract only, full stop -- it never
# looked at GCV/AWS credentials even when they were genuinely configured.
# Handwritten digits are exactly what Tesseract is weakest at.

def test_auto_mode_falls_back_to_tesseract_when_nothing_cloud_is_configured(monkeypatch) -> None:
    from olkalou_engine.historical_ocr import _engine_set

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    settings = Settings(ENGINE_ROOT=REPO_ROOT)  # gcv_credentials_json defaults to None
    engines = _engine_set("auto", settings)
    assert all(e.name != "gcv" and e.name != "textract" for e in engines)


def test_auto_mode_prefers_gcv_when_credentials_are_configured(monkeypatch, tmp_path: Path) -> None:
    """The core of the fix: auto must actually TRY a configured cloud engine,
    not silently ignore it the way it used to. Uses a fake engine class so
    this is verified regardless of whether the real google-cloud-vision SDK
    happens to be installed in the environment running the test."""
    import olkalou_engine.historical_ocr as hocr

    class FakeGCV:
        name = "gcv"
        def __init__(self, credentials_json=None):
            self.credentials_json = credentials_json
        def available(self):
            return True

    monkeypatch.setattr(hocr, "GoogleVisionPageEngine", FakeGCV)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    creds_path = tmp_path / "fake-creds.json"
    creds_path.write_text("{}")
    settings = Settings(ENGINE_ROOT=REPO_ROOT, GCV_CREDENTIALS_JSON=str(creds_path))
    engines = hocr._engine_set("auto", settings)
    assert any(isinstance(e, FakeGCV) for e in engines)


def test_auto_mode_tries_textract_when_aws_key_is_present(monkeypatch) -> None:
    import olkalou_engine.historical_ocr as hocr

    class FakeTextract:
        name = "textract"
        def __init__(self, region):
            self.region = region
        def available(self):
            return True

    monkeypatch.setattr(hocr, "TextractPageEngine", FakeTextract)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-key-for-test")
    settings = Settings(ENGINE_ROOT=REPO_ROOT)
    engines = hocr._engine_set("auto", settings)
    assert any(isinstance(e, FakeTextract) for e in engines)


def test_auto_mode_survives_a_configured_but_broken_gcv_engine(monkeypatch, tmp_path: Path) -> None:
    """Credentials are configured but the engine can't actually construct
    (bad key, package genuinely not installed, etc.) -- auto must fail over
    to Tesseract rather than crash the whole sync run. This is exercised for
    real (not mocked): google-cloud-vision is not installed in this test
    environment, so GoogleVisionPageEngine's own constructor raises exactly
    the RuntimeError this fix needs to survive."""
    from olkalou_engine.historical_ocr import _engine_set

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    creds_path = tmp_path / "fake-creds.json"
    creds_path.write_text("{}")
    settings = Settings(ENGINE_ROOT=REPO_ROOT, GCV_CREDENTIALS_JSON=str(creds_path))
    engines = _engine_set("auto", settings)  # must not raise
    assert all(e.name != "gcv" for e in engines)  # correctly excluded, not silently broken


def test_bounded_pilot_writes_outside_production_and_samples_across_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    documents = bundle.election_dir / "documents"
    documents.mkdir(exist_ok=True)
    selected_streams = [bundle.streams[0], bundle.streams[10], bundle.streams[20], bundle.streams[30]]
    for index, stream in enumerate(selected_streams):
        (documents / f"FORM35A_{stream['polling_station_code']}.pdf").write_bytes(
            f"fixture-{index}".encode()
        )

    monkeypatch.setattr("olkalou_engine.historical_ocr._page_count", lambda path: 1)

    def embedded(path: Path, page_no: int) -> str:
        code = next(
            stream["polling_station_code"]
            for stream in selected_streams
            if stream["polling_station_code"] in path.name
        )
        stream = next(item for item in selected_streams if item["polling_station_code"] == code)
        return sample_35a_text(bundle, stream)

    monkeypatch.setattr("olkalou_engine.historical_ocr._embedded_text", embedded)
    pilot_dir = tmp_path / "pilot-output"
    settings = Settings(ENGINE_ROOT=root)
    summary = run_historical_ocr(
        bundle,
        settings,
        engine_mode="embedded",
        output_dir=pilot_dir,
        max_pages=2,
        reconcile_hierarchy=False,
        rebuild=True,
    )

    assert summary["pilot"] is True
    assert summary["pages_available"] == 4
    assert summary["pages_selected"] == 2
    assert summary["pages_processed"] == 2
    assert (pilot_dir / "summary.json").exists()
    assert (pilot_dir / "review_queue.csv").exists()
    assert (pilot_dir / "document_inventory.json").exists()
    assert not (bundle.election_dir / "ocr" / "summary.json").exists()
    assert not (root / "data" / "public").exists()
    assert summary["hierarchy"]["skipped"] is True
