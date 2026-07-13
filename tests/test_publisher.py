from pathlib import Path

from olkalou_engine.config import Settings
from olkalou_engine.db import EngineDB
from olkalou_engine.publisher import Publisher
from olkalou_engine.reference import load_reference
from olkalou_engine.storage import LocalObjectStore


def test_initial_payload_has_144_awaiting(tmp_path: Path):
    root = Path(__file__).parents[1]
    settings = Settings(ENGINE_ROOT=root)
    reference = load_reference(root / "data/reference/candidates.json", root / "data/reference/streams.json")
    publisher = Publisher(
        settings=settings,
        db=EngineDB(tmp_path / "db.sqlite3"),
        reference=reference,
        store=LocalObjectStore(tmp_path / "public", "http://example"),
    )
    payload = publisher.build(simulations=10)
    assert payload["coverage"]["streams_total"] == 144
    assert payload["coverage"]["awaiting"] == 144
    assert payload["reference"]["complete"] is False
