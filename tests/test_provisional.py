from pathlib import Path

from olkalou_engine.db import EngineDB
from olkalou_engine.models import TrustState
from olkalou_engine.provisional import build_provisional
from olkalou_engine.reference import load_reference

ROOT = Path(__file__).parents[1]
REAL_STREAM_A = "091-PENDING001-01"  # RURII, real (placeholder-station) row in data/reference/streams.json
REAL_STREAM_B = "091-PENDING002-01"  # RURII


def _reference():
    return load_reference(ROOT / "data/reference/candidates.json", ROOT / "data/reference/streams.json")


def _add_form_with_result(db: EngineDB, stream_key: str, votes: dict, state: str, rejected: int = 2):
    db.add_form(
        stream_key=stream_key, version=1, form_type="35A", source_url="https://source",
        archive_path="/tmp/f.jpg", public_url="https://cdn/f.jpg", sha256=stream_key.ljust(64, "a"),
        etag=None, last_modified=None,
    )
    db.save_result(stream_key, 1, {"votes": votes, "rejected": rejected})
    db.update_form_state(stream_key, 1, TrustState(state))


def test_empty_db_has_zero_contributing_forms(tmp_path: Path):
    db = EngineDB(tmp_path / "db.sqlite3")
    result = build_provisional(db, _reference())
    assert result["forms_contributing"] == 0
    assert all(c["votes"] == 0 for c in result["candidates"])
    assert result["PROVISIONAL_UNVERIFIED"] is True


def test_quarantined_form_still_contributes():
    """The whole point: unlike Publisher.build(), a QUARANTINED (not yet
    human-reviewed, not yet statutorily validated) form's OCR figures DO
    count here -- that's what makes this 'provisional' rather than
    'verified'."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = EngineDB(Path(d) / "db.sqlite3")
        _add_form_with_result(db, REAL_STREAM_A, {"UDA": 120, "DCP": 80}, "QUARANTINED")
        result = build_provisional(db, _reference())
        assert result["forms_contributing"] == 1
        uda = next(c for c in result["candidates"] if c["id"] == "UDA")
        assert uda["votes"] == 120
        assert result["state_breakdown"] == {"QUARANTINED": 1}


def test_forms_without_any_extraction_result_are_excluded():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = EngineDB(Path(d) / "db.sqlite3")
        # Archived (form image discovered) but never OCR'd -- no results row.
        db.add_form(
            stream_key=REAL_STREAM_A, version=1, form_type="35A", source_url="https://source",
            archive_path="/tmp/f.jpg", public_url="https://cdn/f.jpg", sha256="c" * 64,
            etag=None, last_modified=None,
        )
        result = build_provisional(db, _reference())
        assert result["forms_contributing"] == 0


def test_sums_across_multiple_states_and_streams():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = EngineDB(Path(d) / "db.sqlite3")
        _add_form_with_result(db, REAL_STREAM_A, {"UDA": 100, "DCP": 50}, "QUARANTINED")
        _add_form_with_result(db, REAL_STREAM_B, {"UDA": 40, "DCP": 60}, "PUBLISHED")
        result = build_provisional(db, _reference())
        assert result["forms_contributing"] == 2
        uda = next(c for c in result["candidates"] if c["id"] == "UDA")
        dcp = next(c for c in result["candidates"] if c["id"] == "DCP")
        assert uda["votes"] == 140
        assert dcp["votes"] == 110
        assert result["state_breakdown"] == {"QUARANTINED": 1, "PUBLISHED": 1}


def test_warning_and_flag_always_present():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = EngineDB(Path(d) / "db.sqlite3")
        result = build_provisional(db, _reference())
        assert result["PROVISIONAL_UNVERIFIED"] is True
        assert "NOT AN ELECTION RESULT" in result["warning"]
        assert result["schema"] == "olkalou.provisional.v1"


def test_contributing_streams_are_individually_auditable():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = EngineDB(Path(d) / "db.sqlite3")
        _add_form_with_result(db, REAL_STREAM_A, {"UDA": 5, "DCP": 3}, "QUARANTINED")
        result = build_provisional(db, _reference())
        assert len(result["contributing_streams"]) == 1
        row = result["contributing_streams"][0]
        assert row["stream_key"] == REAL_STREAM_A
        assert row["ward"] == "RURII"
        assert row["votes"] == {"UDA": 5, "DCP": 3}


def test_publisher_public_payload_never_contains_provisional_data(tmp_path: Path):
    """Regression lock: the public payload builder must never gain a
    'provisional' key or otherwise fold unverified OCR sums into what
    reaches data/public/live.json."""
    from olkalou_engine.publisher import Publisher
    from olkalou_engine.storage import LocalObjectStore
    from olkalou_engine.config import Settings

    db = EngineDB(tmp_path / "db.sqlite3")
    _add_form_with_result(db, REAL_STREAM_A, {"UDA": 999, "DCP": 1}, "QUARANTINED")

    settings = Settings(ENGINE_ROOT=ROOT)
    publisher = Publisher(
        settings=settings, db=db, reference=_reference(),
        store=LocalObjectStore(tmp_path / "public", "http://example"),
    )
    payload = publisher.build(simulations=10)
    assert "provisional" not in payload
    assert "PROVISIONAL_UNVERIFIED" not in payload
    # And the QUARANTINED form's 999 votes must NOT have reached the real totals:
    assert payload["totals"]["valid_votes"] == 0
    uda_row = next(c for c in payload["candidates"] if c["id"] == "UDA")
    assert uda_row["votes"] == 0
