from pathlib import Path

from olkalou_engine.reference import load_reference


def test_repository_reference_is_safely_incomplete():
    root = Path(__file__).parents[1]
    bundle = load_reference(root / "data/reference/candidates.json", root / "data/reference/streams.json")
    assert bundle.complete is False
    assert len(bundle.streams.streams) == 144
    assert bundle.streams.register_total == 73480
    assert bundle.production_errors()
