from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from olkalou_engine.config import Settings
from olkalou_engine.realtime import RealtimeSyncManager, create_realtime_app


def make_root(tmp_path: Path, election_id: str = "test-election") -> Path:
    election_dir = tmp_path / "data" / "elections" / election_id
    election_dir.mkdir(parents=True)
    (election_dir / "election.json").write_text(
        json.dumps({"schema": "test", "portal": {"index_url": "https://example.invalid"}}),
        encoding="utf-8",
    )
    (tmp_path / "data" / "elections" / "sync.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "interval_minutes": 5,
                "elections": [election_id],
                "engine": "auto",
                "repository": "owner/repo",
                "workflow_file": "sync.yml",
            }
        ),
        encoding="utf-8",
    )
    public = tmp_path / "data" / "public" / "elections"
    public.mkdir(parents=True)
    (public / f"{election_id}.json").write_text(
        json.dumps(
            {
                "schema": "kenya.election.archive.v1",
                "seq": 10,
                "generated_at": "2026-07-14T00:00:00Z",
                "election_id": election_id,
            }
        ),
        encoding="utf-8",
    )
    (public / "catalog.json").write_text(
        json.dumps(
            {
                "schema": "kenya.election.catalog.v1",
                "default": election_id,
                "elections": [{"id": election_id, "label": "Test"}],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def settings_for(root: Path, election_id: str = "test-election") -> Settings:
    return Settings(
        ENGINE_ROOT=root,
        REALTIME_API_TOKEN="unit-test-secret",
        REALTIME_SCHEDULER_ENABLED=False,
        REALTIME_ELECTIONS=election_id,
        REALTIME_LIVE_ELECTION_ID="different-live-election",
        REALTIME_TRIGGER_COOLDOWN_SECONDS=0,
        PUBLIC_BASE_URL="http://test/data/public",
    )


def wait_complete(manager: RealtimeSyncManager, election_id: str) -> dict:
    deadline = time.time() + 3
    status = manager.status(election_id)
    while status["state"] in {"QUEUED", "RUNNING"} and time.time() < deadline:
        time.sleep(0.02)
        status = manager.status(election_id)
    return status


def test_realtime_job_publishes_progress_and_deduplicates(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    settings = settings_for(root)
    started = threading.Event()
    release = threading.Event()

    def fake_sync(settings, election_id, *, engine_mode, rebuild, progress):
        progress("DISCOVERING", "checking", {"discovered": 1})
        started.set()
        release.wait(timeout=2)
        payload_path = root / "data" / "public" / "elections" / f"{election_id}.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["seq"] = 11
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        return {"state": "UPDATED", "message": "updated"}

    monkeypatch.setattr("olkalou_engine.realtime.sync_election", fake_sync)
    manager = RealtimeSyncManager(settings)
    first = manager.trigger("test-election")
    assert started.wait(timeout=1)
    second = manager.trigger("test-election")
    assert second["job_id"] == first["job_id"]
    release.set()
    status = wait_complete(manager, "test-election")
    assert status["state"] == "COMPLETE"
    assert status["payload_seq"] == 11
    assert status["changed"] is True
    persisted = json.loads(
        (root / "data" / "public" / "realtime" / "status" / "test-election.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["stage"] == "COMPLETE"


def test_realtime_api_requires_owner_token_and_serves_no_store_data(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    settings = settings_for(root)

    def fake_sync(settings, election_id, *, engine_mode, rebuild, progress):
        progress("DISCOVERING", "checking", None)
        return {"state": "NO_CHANGE", "message": "no change"}

    monkeypatch.setattr("olkalou_engine.realtime.sync_election", fake_sync)
    app = create_realtime_app(settings)
    with TestClient(app) as client:
        data = client.get("/api/elections/test-election/data")
        assert data.status_code == 200
        assert data.headers["cache-control"] == "no-store, max-age=0"
        denied = client.post("/api/elections/test-election/sync", json={})
        assert denied.status_code == 401
        accepted = client.post(
            "/api/elections/test-election/sync",
            headers={"Authorization": "Bearer unit-test-secret"},
            json={"engine": "auto", "rebuild": False},
        )
        assert accepted.status_code == 202
        assert accepted.json()["state"] in {"QUEUED", "RUNNING", "COMPLETE"}


def test_realtime_service_refuses_default_token(tmp_path):
    root = make_root(tmp_path)
    settings = Settings(
        ENGINE_ROOT=root,
        REALTIME_API_TOKEN="change-me",
        REALTIME_SCHEDULER_ENABLED=False,
    )
    try:
        create_realtime_app(settings)
    except RuntimeError as exc:
        assert "REALTIME_API_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("default token must be rejected")
