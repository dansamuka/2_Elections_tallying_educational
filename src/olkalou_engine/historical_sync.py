from __future__ import annotations

import json
import os
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .archive import (
    build_archive_payload,
    build_catalog,
    load_historical_bundle,
    run_historical_archive,
)
from .config import Settings
from .historical_ocr import OCR_PIPELINE_VERSION, run_historical_ocr


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


@dataclass(frozen=True)
class SyncPlan:
    enabled: bool
    interval_minutes: int
    election_ids: tuple[str, ...]
    engine: str
    repository: str
    workflow_file: str

    @property
    def workflow_url(self) -> str:
        return f"https://github.com/{self.repository}/actions/workflows/{self.workflow_file}"


def load_sync_plan(root: Path) -> SyncPlan:
    path = root / "data" / "elections" / "sync.json"
    if not path.exists():
        elections = tuple(
            sorted(profile.parent.name for profile in (root / "data" / "elections").glob("*/election.json"))
        )
        return SyncPlan(
            enabled=False,
            interval_minutes=5,
            election_ids=elections,
            engine="auto",
            repository="dansamuka/2_Elections_tallying_educational",
            workflow_file="sync-historical-forms.yml",
        )
    raw = _read_json(path)
    return SyncPlan(
        enabled=bool(raw.get("enabled", True)),
        interval_minutes=max(5, int(raw.get("interval_minutes", 5))),
        election_ids=tuple(str(value) for value in raw.get("elections", [])),
        engine=str(raw.get("engine", "auto")),
        repository=str(raw.get("repository", "dansamuka/2_Elections_tallying_educational")),
        workflow_file=str(raw.get("workflow_file", "sync-historical-forms.yml")),
    )


class SyncLock(AbstractContextManager["SyncLock"]):
    """Small cross-platform lock preventing overlapping local/manual syncs."""

    def __init__(self, path: Path, stale_after_seconds: int = 45 * 60):
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> "SyncLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age > self.stale_after_seconds:
                self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("another historical-election sync is already running") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": utc_now_iso()}))
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
        return None


def _status_path(root: Path, election_id: str) -> Path:
    return root / "data" / "elections" / election_id / "sync_status.json"


def load_sync_status(root: Path, election_id: str) -> dict[str, Any]:
    path = _status_path(root, election_id)
    if not path.exists():
        return {
            "schema": "kenya.election.portal-sync.v1",
            "election_id": election_id,
            "state": "NEVER_RUN",
            "last_started_at": None,
            "last_completed_at": None,
            "last_changed_at": None,
            "message": "The IEBC portal sync has not run for this election.",
        }
    return _read_json(path)


def _public_payload_exists(root: Path, election_id: str) -> bool:
    return (root / "data" / "public" / "elections" / f"{election_id}.json").exists()


def sync_election(
    settings: Settings,
    election_id: str,
    *,
    engine_mode: str = "auto",
    rebuild: bool = False,
    links_only: bool = False,
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    # Election-specific cross-process locking keeps a Malava/ Banissa job from
    # blocking Ol Kalou while still preventing two writers from touching the
    # same election directory at once.
    lock_path = settings.root / "data" / "state" / f"historical-sync-{election_id}.lock"
    with SyncLock(lock_path, stale_after_seconds=3 * 60 * 60):
        return _sync_election_unlocked(
            settings,
            election_id,
            engine_mode=engine_mode,
            rebuild=rebuild,
            links_only=links_only,
            progress=progress,
        )


def _sync_election_unlocked(
    settings: Settings,
    election_id: str,
    *,
    engine_mode: str = "auto",
    rebuild: bool = False,
    links_only: bool = False,
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    root = settings.root
    bundle = load_historical_bundle(root, election_id)
    started_at = utc_now_iso()
    previous = load_sync_status(root, election_id)
    def emit(stage: str, message: str, details: dict[str, Any] | None = None) -> None:
        if progress:
            progress(stage, message, details)

    try:
        emit("DISCOVERING", "Checking the IEBC portal and downloading only new or changed forms.")
        archive_result = run_historical_archive(
            bundle,
            user_agent=settings.portal_user_agent,
            download=not links_only,
        )
        archive_changed = bool(archive_result.get("changed"))
        emit(
            "ARCHIVED",
            "Portal check completed; source-form inventory is current.",
            {
                "discovered": archive_result.get("discovered"),
                "downloaded": archive_result.get("downloaded"),
                "new_downloads": archive_result.get("new_downloads"),
                "changed_downloads": archive_result.get("changed_downloads"),
                "unmatched": archive_result.get("unmatched"),
            },
        )
        ocr_summary_path = bundle.election_dir / "ocr" / "summary.json"
        existing_ocr_version = None
        if ocr_summary_path.exists():
            try:
                existing_ocr_version = _read_json(ocr_summary_path).get("pipeline_version")
            except (OSError, ValueError, TypeError):
                existing_ocr_version = None
        should_run_ocr = (
            rebuild
            or archive_changed
            or not ocr_summary_path.exists()
            or existing_ocr_version != OCR_PIPELINE_VERSION
        )
        ocr_result: dict[str, Any] | None = None
        if should_run_ocr and not links_only:
            emit("OCR", "Running cached, field-isolated OCR only where extraction is new or stale.")
            ocr_result = run_historical_ocr(
                bundle,
                settings,
                engine_mode=engine_mode,
                rebuild=rebuild,
            )
        payload_changed = archive_changed or should_run_ocr or not _public_payload_exists(root, election_id)
        emit("BUILDING", "Building the current election JSON with an atomic file replacement.")
        if payload_changed:
            payload = build_archive_payload(bundle)
            build_catalog(root)
        else:
            payload = json.loads(bundle.public_path.read_text(encoding="utf-8"))

        completed_at = utc_now_iso()
        emit("PUBLISHING", "Publishing the updated election payload and sync status.")
        status = {
            "schema": "kenya.election.portal-sync.v1",
            "election_id": election_id,
            "state": "UPDATED" if payload_changed else "NO_CHANGE",
            "last_started_at": started_at,
            "last_completed_at": completed_at,
            "last_changed_at": completed_at if payload_changed else previous.get("last_changed_at"),
            "portal_url": bundle.profile["portal"]["index_url"],
            "engine_mode": engine_mode,
            "archive": archive_result,
            "ocr": {
                "ran": ocr_result is not None,
                "pages_processed": (ocr_result or {}).get("pages_processed", 0),
                "review_rows": (ocr_result or {}).get("review_rows", 0),
                "errors": len((ocr_result or {}).get("errors", [])),
            },
            "coverage": payload.get("coverage", {}),
            "message": (
                "New or changed IEBC forms were downloaded and the dashboard was rebuilt."
                if payload_changed
                else "The IEBC portal was checked; no new form files were found."
            ),
        }
        # Avoid a repository commit every five minutes when nothing changes. Persist a
        # no-change check only locally; scheduled Actions report it in their run summary.
        if payload_changed or previous.get("state") not in {"UPDATED", "NO_CHANGE"}:
            _write_json(_status_path(root, election_id), status)
            # Rebuild once more so the public payload contains the persisted status.
            payload = build_archive_payload(bundle)
            build_catalog(root)
        return status
    except Exception as exc:
        failure = {
            "schema": "kenya.election.portal-sync.v1",
            "election_id": election_id,
            "state": "ERROR",
            "last_started_at": started_at,
            "last_completed_at": utc_now_iso(),
            "last_changed_at": previous.get("last_changed_at"),
            "portal_url": bundle.profile["portal"]["index_url"],
            "engine_mode": engine_mode,
            "message": str(exc),
        }
        if previous.get("state") != "ERROR" or previous.get("message") != str(exc):
            _write_json(_status_path(root, election_id), failure)
            build_archive_payload(bundle)
            build_catalog(root)
        raise


def sync_elections(
    settings: Settings,
    election_ids: Iterable[str],
    *,
    engine_mode: str = "auto",
    rebuild: bool = False,
    links_only: bool = False,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(str(value) for value in election_ids))
    if not ids:
        raise ValueError("no historical elections are configured for portal sync")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for election_id in ids:
        try:
            results.append(
                sync_election(
                    settings,
                    election_id,
                    engine_mode=engine_mode,
                    rebuild=rebuild,
                    links_only=links_only,
                )
            )
        except Exception as exc:
            failures.append({"election_id": election_id, "message": str(exc)})
    return {
        "schema": "kenya.election.portal-sync-run.v1",
        "started_at": results[0]["last_started_at"] if results else utc_now_iso(),
        "completed_at": utc_now_iso(),
        "requested": ids,
        "results": results,
        "failures": failures,
        "changed": any(row.get("state") == "UPDATED" for row in results),
    }
