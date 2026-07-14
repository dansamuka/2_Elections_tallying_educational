from __future__ import annotations

import json
import shutil
import zipfile
from io import BytesIO
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
    assert plan.election_ids == ("banissa-2025", "malava-2025", "ol-kalou-2026")
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


def test_historical_archive_accepts_verified_constituency_download_all_bundle(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    form = PortalForm(
        source_url="https://forms.example/index.php?r=site%2Fdownload-all&p=2&ft=1&lv=2",
        source_label="BANISSA Download All",
        stream_key=None,
        station_name=None,
        stream_no=None,
        form_type="35A",
    )
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for index in range(81):
            archive.writestr(f"banissa-form-35a-{index + 1:03d}.pdf", b"%PDF-1.4 fixture")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def conditional_get(self, url, etag=None, last_modified=None):
            self.calls += 1
            if self.calls == 1:
                return FetchResult(200, b"<html>BANISSA 81 of 81</html>", {"etag": "index-1"}, url)
            return FetchResult(
                200, payload.getvalue(), {"content-type": "application/zip"}, url
            )

        def reported_counts(self, html):
            return 81, 81

        def discover(self, html, base_url=None):
            return [form]

        def close(self):
            return None

    monkeypatch.setattr("olkalou_engine.archive.PortalClient", FakeClient)
    result = run_historical_archive(bundle, user_agent="test", download=True)
    assert result["changed"] is True
    assert result["discovered"] == 81
    assert result["downloaded"] == 81
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    entry = manifest["forms"][form.source_url]
    assert len(entry["extracted_files"]) == 81


def test_historical_archive_rejects_wrong_sized_download_all_bundle_before_archiving(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    form = PortalForm(
        source_url="https://forms.example/index.php?r=site%2Fdownload-all&p=2&ft=1&lv=2",
        source_label="BANISSA Download All",
        stream_key=None,
        station_name=None,
        stream_no=None,
        form_type="35A",
    )
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for index in range(82):
            archive.writestr(f"form-{index + 1:03d}.pdf", b"%PDF fixture")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def conditional_get(self, url, etag=None, last_modified=None):
            self.calls += 1
            if self.calls == 1:
                return FetchResult(200, b"<html>BANISSA 81 of 81</html>", {}, url)
            return FetchResult(200, payload.getvalue(), {"content-type": "application/zip"}, url)

        def reported_counts(self, html):
            return 81, 81

        def discover(self, html, base_url=None):
            return [form]

        def close(self):
            return None

    monkeypatch.setattr("olkalou_engine.archive.PortalClient", FakeClient)
    try:
        run_historical_archive(bundle, user_agent="test", download=True)
        raise AssertionError("wrong-sized bundle must be rejected")
    except RuntimeError as exc:
        assert "expected exactly 81" in str(exc)
    assert not bundle.manifest_path.exists()
    assert not any((root / "data" / "public" / "elections" / "banissa-2025" / "forms").rglob("*"))


def test_sync_plan_includes_banissa_and_ol_kalou() -> None:
    plan = load_sync_plan(REPO_ROOT)
    assert plan.election_ids == ("banissa-2025", "malava-2025", "ol-kalou-2026")


def test_ol_kalou_live_profile_allows_unresolved_atomic_reference() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "ol-kalou-2026")
    assert bundle.profile["mode"] == "LIVE"
    assert bundle.profile["election"]["county"] == "NYANDARUA"
    assert bundle.profile["portal"]["detail_url"].endswith("id=141&ft=&p=2&es=")
    assert len(bundle.streams) == 144
    assert sum(1 for row in bundle.streams if row["registered"] is None) == 144
    assert sum(row["expected_forms"] for row in bundle.profile["portal"]["hierarchy"]["wards"]) == 144


def test_ol_kalou_public_payload_is_pre_poll_and_reference_gated() -> None:
    from olkalou_engine.archive import build_archive_payload

    bundle = load_historical_bundle(REPO_ROOT, "ol-kalou-2026")
    payload = build_archive_payload(bundle)
    assert payload["mode"] == "LIVE"
    assert payload["status"] == "PRE_POLL"
    assert payload["reference"]["complete"] is False
    assert payload["coverage"]["streams_total"] == 144
    assert payload["archive"]["forms_expected"] == 144
    assert payload["archive"]["tally_source"] == "NO_VERIFIED_TALLY"


def test_ol_kalou_pre_poll_zero_forms_is_a_valid_sync_state(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    target_parent = root / "data" / "elections"
    target_parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "data" / "elections" / "ol-kalou-2026", target_parent / "ol-kalou-2026")
    bundle = load_historical_bundle(root, "ol-kalou-2026")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def conditional_get(self, url, etag=None, last_modified=None):
            return FetchResult(200, b"<html>OL KALOU 0 of 144</html>", {}, url)

        def reported_counts(self, html):
            return 0, 144

        def discover(self, html, base_url=None):
            return []

        def close(self):
            return None

    monkeypatch.setattr("olkalou_engine.archive.PortalClient", FakeClient)
    result = run_historical_archive(bundle, user_agent="test", download=True)
    assert result["status"] == "UPDATED"
    assert result["discovered"] == 0
    assert result["downloaded"] == 0
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["portal_reported"] == 0
    assert manifest["portal_expected"] == 144


def test_unchanged_index_retries_incomplete_manifest_download(tmp_path: Path, monkeypatch) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    stream = bundle.streams[0]
    source_url = "https://forms.example/banissa/retry-me.pdf"
    manifest = {
        "schema": "kenya.election.forms-manifest.v1",
        "election_id": "banissa-2025",
        "index": {"etag": "same-index"},
        "discovered_count": 1,
        "matched_count": 1,
        "downloaded_count": 0,
        "unmatched": [],
        "forms": {
            source_url: {
                "stream_key": stream["stream_key"],
                "polling_station_code": stream["polling_station_code"],
                "source_url": source_url,
                "source_label": f"BANISSA Form 35A {stream['polling_station_code']}",
                "form_type": "35A",
                "download_error": "HTTP 503",
            }
        },
    }
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def conditional_get(self, url, etag=None, last_modified=None):
            self.calls += 1
            if self.calls == 1:
                return FetchResult(304, None, {}, url)
            return FetchResult(200, b"%PDF-1.4 recovered", {"content-type": "application/pdf"}, url)

        def close(self):
            return None

    monkeypatch.setattr("olkalou_engine.archive.PortalClient", FakeClient)
    result = run_historical_archive(bundle, user_agent="test", download=True)
    assert result["status"] == "UPDATED"
    assert result["downloaded"] == 1
    assert result["failed_downloads"] == 0
    assert result["new_downloads"] == 1
    updated = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    entry = updated["forms"][source_url]
    assert entry["sha256"]
    assert (root / entry["archive_path"]).exists()
