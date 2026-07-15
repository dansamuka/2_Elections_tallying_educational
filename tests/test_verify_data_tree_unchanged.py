from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "verify_data_tree_unchanged.py"
SPEC = importlib.util.spec_from_file_location(
    "verify_data_tree_unchanged",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_data_tree_snapshot_is_stable_when_files_are_unchanged(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "one.json").write_text("one", encoding="utf-8")
    before = MODULE.build_snapshot(data)
    after = MODULE.build_snapshot(data)
    report = MODULE.compare_snapshots(before, after)
    assert report["unchanged"] is True
    assert report["added"] == []
    assert report["removed"] == []
    assert report["changed"] == []


def test_data_tree_diff_reports_added_removed_and_changed_files(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "removed.json").write_text("remove", encoding="utf-8")
    (data / "changed.json").write_text("before", encoding="utf-8")
    before = MODULE.build_snapshot(data)

    (data / "removed.json").unlink()
    (data / "changed.json").write_text("after", encoding="utf-8")
    (data / "added.json").write_text("add", encoding="utf-8")

    after = MODULE.build_snapshot(data)
    report = MODULE.compare_snapshots(before, after)
    assert report["unchanged"] is False
    assert report["added"] == ["added.json"]
    assert report["removed"] == ["removed.json"]
    assert [item["path"] for item in report["changed"]] == ["changed.json"]
