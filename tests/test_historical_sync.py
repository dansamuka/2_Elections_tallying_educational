from __future__ import annotations

import json
import shutil
from pathlib import Path

from olkalou_engine.archive import load_historical_bundle, run_historical_archive
from olkalou_engine.historical_sync import SyncLock, load_sync_plan
from olkalou_engine.models import PortalForm
from olkalou_engine.portal import FetchResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_banissa(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = REPO_ROOT / "data" / "elections" / "banissa-2025"
    target = root / "data" / "elections" / "banissa-2025"
    target.parent.mkdir(parents=True)
    shutil.copytree(source, target)
    shutil.copy2(REPO_ROOT / "data" / "elections" / "sync.json", target.parent / "sync.json")
    return root


def test_sync_plan_targets_existing_repository() -> None:
    plan = load_sync_plan(REPO_ROOT)
    assert plan.enabled is True
    assert plan.interval_minutes == 5
    assert plan.election_ids == ("banissa-2025",)
    assert plan.repository == "dansamuka/2_Elections_tallying_educational"
    assert plan.workflow_url.endswith("sync-historical-forms.yml")


def test_sync_lock_rejects_overlap(tmp_path: Path) -> None:
    path = tmp_path / "sync.lock"
    with SyncLock(path):
        try:
            with SyncLock(path):
                raise AssertionError("second lock should not be acquired")
        except RuntimeError as exc:
            assert "already running" in str(exc)
    assert not path.exists()


def test_historical_archive_downloads_and_versions_new_form(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    stream = bundle.streams[0]
    form = PortalForm(
        source_url="https://forms.example/banissa/35a-1.pdf",
        source_label=f"BANISSA Form 35A {stream['polling_station_code']}",
        stream_key=stream["stream_key"],
        station_name=stream["station_name"],
        stream_no=stream["stream_no"],
        form_type="35A",
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def conditional_get(self, url, etag=None, last_modified=None):
            self.calls += 1
            if self.calls == 1:
                return FetchResult(200, b"<html>BANISSA</html>", {"etag": "index-1"}, url)
            return FetchResult(200, b"%PDF-1.4 fixture", {"content-type": "application/pdf"}, url)

        def reported_counts(self, html):
            return 1, 1

        def discover(self, html, base_url=None):
            return [form]

        def close(self):
            return None

    monkeypatch.setattr("olkalou_engine.archive.PortalClient", FakeClient)
    result = run_historical_archive(bundle, user_agent="test", download=True)
    assert result["changed"] is True
    assert result["new_downloads"] == 1
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    entry = manifest["forms"][form.source_url]
    assert entry["stream_key"] == stream["stream_key"]
    assert entry["version"] == 1
    assert len(entry["versions"]) == 1
    assert (root / entry["archive_path"]).exists()


def test_scheduled_workflow_is_five_minute_and_manual() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "sync-historical-forms.yml").read_text(encoding="utf-8")
    assert 'cron: "2/5 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "archive-sync" in workflow
    assert "tesseract-ocr" in workflow
