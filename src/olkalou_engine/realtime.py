from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .archive import build_catalog
from .config import Settings, get_settings
from .db import EngineDB
from .historical_sync import load_sync_plan, sync_election, utc_now_iso
from .public_mirror import PublicDataMirror
from .publisher import Publisher
from .reference import load_reference
from .storage import build_store

LOGGER = logging.getLogger(__name__)
ALLOWED_ENGINES = {"auto", "embedded", "tesseract", "gcv", "textract", "dual-cloud"}
RUNNING_STATES = {"QUEUED", "RUNNING"}


class SyncRequest(BaseModel):
    engine: str | None = None
    rebuild: bool = False


class RealtimeSyncManager:
    """Runs election-specific incremental sync jobs without a Pages deployment.

    Jobs are deduplicated per election. The live election can therefore be checked
    every 15-30 seconds while slower historical benchmarks remain outside the
    critical path. Each status transition is published as a tiny JSON object so the
    browser can display progress while a form is downloading/OCRing.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.plan = load_sync_plan(settings.root)
        self.mirror = PublicDataMirror(settings)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        self._scheduler: threading.Thread | None = None
        self._last_triggered: dict[str, float] = {}
        self._load_statuses()

    @property
    def election_ids(self) -> tuple[str, ...]:
        configured = self.settings.realtime_election_list
        return configured or self.plan.election_ids

    def start(self) -> None:
        if not self.settings.realtime_scheduler_enabled or self._scheduler:
            return
        self._scheduler = threading.Thread(
            target=self._scheduler_loop,
            name="realtime-election-scheduler",
            daemon=True,
        )
        self._scheduler.start()

    def stop(self) -> None:
        self._stop.set()
        if self._scheduler and self._scheduler.is_alive():
            self._scheduler.join(timeout=5)

    def trigger(
        self,
        election_id: str,
        *,
        engine: str | None = None,
        rebuild: bool = False,
        reason: str = "manual",
    ) -> dict[str, Any]:
        self._validate_election(election_id)
        engine = engine or self.settings.realtime_engine or self.plan.engine
        if engine not in ALLOWED_ENGINES:
            raise ValueError(f"unsupported OCR engine: {engine}")
        now = time.monotonic()
        with self._lock:
            existing = self._jobs.get(election_id)
            if existing and existing.get("state") in RUNNING_STATES:
                return dict(existing)
            cooldown = self.settings.realtime_trigger_cooldown_seconds
            last = self._last_triggered.get(election_id, 0.0)
            if reason == "manual" and now - last < cooldown:
                status = self.status(election_id)
                status["deduplicated"] = True
                status["message"] = (
                    f"A check was requested less than {cooldown}s ago; returning its latest status."
                )
                return status
            self._last_triggered[election_id] = now
            status = self._new_status(election_id, engine, rebuild, reason)
            self._jobs[election_id] = status
            self._persist(status)
            thread = threading.Thread(
                target=self._run_job,
                args=(election_id, engine, rebuild),
                name=f"realtime-sync-{election_id}",
                daemon=True,
            )
            self._threads[election_id] = thread
            thread.start()
            return dict(status)

    def status(self, election_id: str) -> dict[str, Any]:
        self._validate_election(election_id)
        with self._lock:
            status = self._jobs.get(election_id)
            if status:
                return dict(status)
        path = self._status_path(election_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {
            "schema": "kenya.election.realtime-status.v1",
            "seq": 0,
            "job_id": None,
            "election_id": election_id,
            "state": "IDLE",
            "stage": "IDLE",
            "message": "No realtime check has run in this deployment.",
            "requested_at": None,
            "started_at": None,
            "completed_at": None,
            "payload_seq": self._payload_seq(election_id),
            "changed": False,
        }

    def read_election(self, election_id: str) -> dict[str, Any]:
        self._validate_election(election_id)
        path = self.settings.root / "data" / "public" / "elections" / f"{election_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def read_catalog(self) -> dict[str, Any]:
        path = self.settings.root / "data" / "public" / "elections" / "catalog.json"
        if not path.exists():
            build_catalog(self.settings.root)
        return json.loads(path.read_text(encoding="utf-8"))

    def read_live(self) -> dict[str, Any]:
        if not self.settings.live_path.exists():
            self._publish_live_payload()
        return json.loads(self.settings.live_path.read_text(encoding="utf-8"))

    def _run_job(self, election_id: str, engine: str, rebuild: bool) -> None:
        self._update(
            election_id,
            state="RUNNING",
            stage="STARTING",
            started_at=utc_now_iso(),
            message="Starting election-specific portal check.",
        )

        def progress(stage: str, message: str, details: dict[str, Any] | None = None) -> None:
            self._update(
                election_id,
                state="RUNNING",
                stage=stage,
                message=message,
                details=details or {},
            )

        try:
            result = sync_election(
                self.settings,
                election_id,
                engine_mode=engine,
                rebuild=rebuild,
                progress=progress,
            )
            progress("MIRRORING", "Publishing current JSON outside the GitHub Pages build path.")
            election_payload = self.mirror.publish_election(election_id)
            self.mirror.publish_catalog()
            live_payload: dict[str, Any] | None = None
            if election_id == self.settings.realtime_live_election_id:
                progress("LIVE_PAYLOAD", "Refreshing the live tally JSON from current verified state.")
                live_payload = self._publish_live_payload()
            self._update(
                election_id,
                state="COMPLETE",
                stage="COMPLETE",
                completed_at=utc_now_iso(),
                changed=bool(result.get("state") == "UPDATED"),
                payload_seq=int(election_payload.get("seq", 0) or 0),
                live_payload_seq=int((live_payload or {}).get("seq", 0) or 0),
                message=result.get("message") or "Realtime election check completed.",
                result=result,
            )
        except Exception as exc:  # pragma: no cover - tested through monkeypatched failures
            LOGGER.exception("realtime sync failed for %s", election_id)
            self._update(
                election_id,
                state="ERROR",
                stage="ERROR",
                completed_at=utc_now_iso(),
                message=str(exc),
                error=type(exc).__name__,
            )

    def _publish_live_payload(self) -> dict[str, Any]:
        reference = load_reference(self.settings.candidates_path, self.settings.streams_path)
        publisher = Publisher(
            settings=self.settings,
            db=EngineDB(self.settings.db_path),
            reference=reference,
            store=build_store(self.settings),
        )
        payload = publisher.publish(simulations=500)
        # Keep an atomic local canonical copy even when Publisher is writing directly
        # to R2/S3. This lets the API and a local fallback server return the same
        # payload without depending on object-storage read availability.
        path = self.settings.live_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(path)
        self.mirror.publish_live()
        return payload

    def _scheduler_loop(self) -> None:
        due: dict[str, float] = {election_id: 0.0 for election_id in self.election_ids}
        while not self._stop.wait(1):
            now = time.monotonic()
            for election_id in self.election_ids:
                if now < due.get(election_id, 0.0):
                    continue
                try:
                    self.trigger(election_id, reason="scheduled")
                except Exception:
                    LOGGER.exception("could not schedule realtime sync for %s", election_id)
                interval = (
                    self.settings.realtime_poll_seconds
                    if election_id == self.settings.realtime_live_election_id
                    else self.settings.realtime_archive_poll_seconds
                )
                due[election_id] = now + interval

    def _new_status(
        self, election_id: str, engine: str, rebuild: bool, reason: str
    ) -> dict[str, Any]:
        return {
            "schema": "kenya.election.realtime-status.v1",
            "seq": time.time_ns() // 1_000_000,
            "job_id": uuid.uuid4().hex,
            "election_id": election_id,
            "state": "QUEUED",
            "stage": "QUEUED",
            "reason": reason,
            "engine": engine,
            "rebuild": rebuild,
            "requested_at": utc_now_iso(),
            "started_at": None,
            "completed_at": None,
            "payload_seq": self._payload_seq(election_id),
            "changed": False,
            "message": "Realtime check queued.",
        }

    def _update(self, election_id: str, **patch: Any) -> dict[str, Any]:
        with self._lock:
            current = dict(self._jobs.get(election_id) or self.status(election_id))
            current.update(patch)
            current["seq"] = max(
                int(current.get("seq", 0)) + 1,
                time.time_ns() // 1_000_000,
            )
            self._jobs[election_id] = current
            self._persist(current)
            return dict(current)

    def _persist(self, status: dict[str, Any]) -> None:
        path = self._status_path(status["election_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp.replace(path)
        try:
            self.mirror.publish_status(status["election_id"], status)
        except Exception:
            # A storage outage must not abort local portal/OCR processing. The final
            # status will retry during the next transition and the local API remains live.
            LOGGER.exception("could not mirror realtime status")

    def _load_statuses(self) -> None:
        status_dir = self.settings.root / "data" / "public" / "realtime" / "status"
        if not status_dir.exists():
            return
        for path in status_dir.glob("*.json"):
            try:
                status = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            # A process restart cannot resume an in-memory thread. Make that state
            # explicit instead of leaving the browser spinning forever.
            if status.get("state") in RUNNING_STATES:
                status.update(
                    state="INTERRUPTED",
                    stage="INTERRUPTED",
                    completed_at=utc_now_iso(),
                    message="The realtime service restarted before this job completed; retry the check.",
                )
            self._jobs[str(status.get("election_id") or path.stem)] = status

    def _validate_election(self, election_id: str) -> None:
        profile = self.settings.root / "data" / "elections" / election_id / "election.json"
        if not profile.exists():
            raise KeyError(election_id)

    def _payload_seq(self, election_id: str) -> int:
        path = self.settings.root / "data" / "public" / "elections" / f"{election_id}.json"
        try:
            return int(json.loads(path.read_text(encoding="utf-8")).get("seq", 0) or 0)
        except (OSError, ValueError, TypeError):
            return 0

    def _status_path(self, election_id: str) -> Path:
        return (
            self.settings.root
            / "data"
            / "public"
            / "realtime"
            / "status"
            / f"{election_id}.json"
        )


def create_realtime_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.realtime_api_token == "change-me":
        raise RuntimeError(
            "REALTIME_API_TOKEN is still 'change-me'. Set a unique token before exposing "
            "the realtime trigger endpoint. The token is entered by an owner in the browser "
            "and is never embedded in the static site."
        )
    manager = RealtimeSyncManager(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="Election Realtime Sync Gateway", version="1.0.0", lifespan=lifespan)
    origins = settings.realtime_cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {settings.realtime_api_token}":
            raise HTTPException(status_code=401, detail="Invalid realtime API token")

    def election_or_404(election_id: str) -> str:
        try:
            manager._validate_election(election_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown election id") from exc
        return election_id

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "OK",
            "scheduler_enabled": settings.realtime_scheduler_enabled,
            "live_election": settings.realtime_live_election_id,
            "poll_seconds": settings.realtime_poll_seconds,
            "elections": manager.election_ids,
            "object_storage": bool(settings.s3_bucket),
        }

    @app.get("/api/catalog")
    def catalog() -> JSONResponse:
        return _json_response(manager.read_catalog())

    @app.get("/api/live")
    def live() -> JSONResponse:
        return _json_response(manager.read_live())

    @app.get("/api/elections/{election_id}/data")
    def election_data(election_id: str) -> JSONResponse:
        election_or_404(election_id)
        try:
            return _json_response(manager.read_election(election_id))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Election payload has not been built") from exc

    @app.get("/api/elections/{election_id}/status")
    def election_status(election_id: str) -> JSONResponse:
        election_or_404(election_id)
        return _json_response(manager.status(election_id))

    @app.get("/api/elections/{election_id}/wait")
    def wait_for_update(
        election_id: str,
        after_seq: int = Query(default=0, ge=0),
        timeout: int = Query(default=25, ge=1, le=30),
    ) -> JSONResponse:
        election_or_404(election_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = manager.status(election_id)
            if int(status.get("seq", 0)) > after_seq or status.get("state") not in RUNNING_STATES:
                return _json_response(status)
            time.sleep(0.5)
        return _json_response(manager.status(election_id))

    @app.post(
        "/api/elections/{election_id}/sync",
        dependencies=[Depends(require_token)],
        status_code=202,
    )
    def trigger_sync(election_id: str, request: SyncRequest) -> JSONResponse:
        election_or_404(election_id)
        try:
            status = manager.trigger(
                election_id,
                engine=request.engine,
                rebuild=request.rebuild,
                reason="manual",
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _json_response(status, status_code=202)

    app.state.sync_manager = manager
    return app


def _json_response(payload: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
