from pathlib import Path

from olkalou_engine.db import EngineDB
from olkalou_engine.models import ReviewEntry, StreamReference
from olkalou_engine.review import submit_review
from olkalou_engine.validation import Validator


REFERENCE = StreamReference(
    stream_key="091-001-01",
    station_code="001",
    station_name="TEST SCHOOL",
    stream_no=1,
    ward_code="0453",
    ward_name="KARAU",
    registered=100,
    reference_status="VERIFIED",
)
VALIDATOR = Validator()


def add_form(db: EngineDB):
    db.add_form(
        stream_key="091-001-01",
        version=1,
        form_type="35A",
        source_url="https://source",
        archive_path="/tmp/form.jpg",
        public_url="https://cdn/form.jpg",
        sha256="b" * 64,
        etag=None,
        last_modified=None,
    )
    return db.get_form("091-001-01", 1)


def entry(reviewer: str, uda: int = 10, *, po_valid: int | None = None):
    po_valid = uda + 8 if po_valid is None else po_valid
    return ReviewEntry(
        stream_key="091-001-01",
        form_version=1,
        reviewer_id=reviewer,
        votes={"UDA": uda, "DCP": 8},
        rejected=1,
        registered_form=100,
        po_total_valid=po_valid,
        total_cast_form=uda + 9,
    )


def submit(db: EngineDB, item: ReviewEntry, row: dict):
    return submit_review(db, item, row, reference=REFERENCE, validator=VALIDATOR)


def test_double_entry_publishes(tmp_path: Path):
    db = EngineDB(tmp_path / "db.sqlite3")
    row = add_form(db)
    first = submit(db, entry("reviewer-a"), row)
    second = submit(db, entry("reviewer-b"), row)
    assert first.status == "PENDING_SECOND_ENTRY"
    assert second.status == "PUBLISHED"
    assert db.get_form("091-001-01", 1)["state"] == "PUBLISHED"


def test_mismatch_conflicts(tmp_path: Path):
    db = EngineDB(tmp_path / "db.sqlite3")
    row = add_form(db)
    submit(db, entry("reviewer-a"), row)
    outcome = submit(db, entry("reviewer-b", uda=11), row)
    assert outcome.status == "MISMATCH"
    assert db.get_form("091-001-01", 1)["state"] == "CONFLICTED"


def test_matching_entries_with_failed_statutory_check_remain_quarantined(tmp_path: Path):
    db = EngineDB(tmp_path / "db.sqlite3")
    row = add_form(db)
    submit(db, entry("reviewer-a", po_valid=99), row)
    outcome = submit(db, entry("reviewer-b", po_valid=99), row)
    assert outcome.status == "QUARANTINED"
    assert db.get_form("091-001-01", 1)["state"] == "QUARANTINED"
