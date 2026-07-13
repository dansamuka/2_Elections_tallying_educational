from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ReviewEntry, TrustState, utc_now_iso


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_key TEXT NOT NULL,
  version INTEGER NOT NULL,
  form_type TEXT NOT NULL DEFAULT '35A',
  source_url TEXT NOT NULL,
  archive_path TEXT NOT NULL,
  public_url TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  etag TEXT,
  last_modified TEXT,
  discovered_at TEXT NOT NULL,
  state TEXT NOT NULL,
  verification TEXT NOT NULL DEFAULT 'NONE',
  UNIQUE(stream_key, version),
  UNIQUE(sha256)
);

CREATE TABLE IF NOT EXISTS results (
  stream_key TEXT NOT NULL,
  version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  validation_json TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(stream_key, version)
);

CREATE TABLE IF NOT EXISTS review_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stream_key TEXT NOT NULL,
  version INTEGER NOT NULL,
  reviewer_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  UNIQUE(stream_key, version, reviewer_id)
);

CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  stream_key TEXT NOT NULL,
  field TEXT NOT NULL,
  from_value TEXT,
  to_value TEXT,
  reason TEXT NOT NULL,
  prior_form_url TEXT,
  new_form_url TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  stream_key TEXT NOT NULL,
  code TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  form_url TEXT
);

CREATE TABLE IF NOT EXISTS heartbeats (
  worker_id TEXT PRIMARY KEY,
  at TEXT NOT NULL,
  status TEXT NOT NULL,
  details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class EngineDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def next_version(self, stream_key: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM forms WHERE stream_key = ?",
                (stream_key,),
            ).fetchone()
        return int(row["v"]) + 1

    def find_by_sha(self, sha256: str) -> sqlite3.Row | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM forms WHERE sha256 = ?", (sha256,)).fetchone()

    def add_form(
        self,
        *,
        stream_key: str,
        version: int,
        form_type: str,
        source_url: str,
        archive_path: str,
        public_url: str,
        sha256: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO forms(
                  stream_key, version, form_type, source_url, archive_path, public_url,
                  sha256, etag, last_modified, discovered_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stream_key,
                    version,
                    form_type,
                    source_url,
                    archive_path,
                    public_url,
                    sha256,
                    etag,
                    last_modified,
                    utc_now_iso(),
                    TrustState.ARCHIVED.value,
                ),
            )

    def update_form_state(
        self, stream_key: str, version: int, state: TrustState, verification: str | None = None
    ) -> None:
        with self.connection() as conn:
            if verification is None:
                conn.execute(
                    "UPDATE forms SET state = ? WHERE stream_key = ? AND version = ?",
                    (state.value, stream_key, version),
                )
            else:
                conn.execute(
                    "UPDATE forms SET state = ?, verification = ? WHERE stream_key = ? AND version = ?",
                    (state.value, verification, stream_key, version),
                )

    def save_result(
        self,
        stream_key: str,
        version: int,
        payload: dict[str, Any],
        validation: dict[str, Any] | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO results(stream_key, version, payload_json, validation_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stream_key, version) DO UPDATE SET
                  payload_json=excluded.payload_json,
                  validation_json=excluded.validation_json,
                  updated_at=excluded.updated_at
                """,
                (
                    stream_key,
                    version,
                    json.dumps(payload, separators=(",", ":")),
                    json.dumps(validation, separators=(",", ":")) if validation else None,
                    utc_now_iso(),
                ),
            )

    def add_review(self, entry: ReviewEntry) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO review_entries(stream_key, version, reviewer_id, payload_json, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stream_key, version, reviewer_id) DO UPDATE SET
                  payload_json=excluded.payload_json,
                  submitted_at=excluded.submitted_at
                """,
                (
                    entry.stream_key,
                    entry.form_version,
                    entry.reviewer_id,
                    entry.model_dump_json(),
                    entry.submitted_at,
                ),
            )

    def reviews_for(self, stream_key: str, version: int) -> list[ReviewEntry]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM review_entries
                WHERE stream_key = ? AND version = ? ORDER BY submitted_at ASC
                """,
                (stream_key, version),
            ).fetchall()
        return [ReviewEntry.model_validate_json(row["payload_json"]) for row in rows]

    def current_forms(self) -> list[dict[str, Any]]:
        query = """
        SELECT f.*, r.payload_json, r.validation_json
        FROM forms f
        JOIN (
          SELECT stream_key, MAX(version) AS version FROM forms GROUP BY stream_key
        ) current ON current.stream_key=f.stream_key AND current.version=f.version
        LEFT JOIN results r ON r.stream_key=f.stream_key AND r.version=f.version
        ORDER BY f.stream_key
        """
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_form(self, stream_key: str, version: int | None = None) -> dict[str, Any] | None:
        base = """
        SELECT f.*, r.payload_json, r.validation_json
        FROM forms f
        LEFT JOIN results r ON r.stream_key=f.stream_key AND r.version=f.version
        WHERE f.stream_key=?
        """
        with self.connection() as conn:
            if version is None:
                row = conn.execute(base + " ORDER BY f.version DESC LIMIT 1", (stream_key,)).fetchone()
            else:
                row = conn.execute(base + " AND f.version=?", (stream_key, version)).fetchone()
        return dict(row) if row else None

    def stream_results(self, stream_key: str, *, before_version: int | None = None) -> list[dict[str, Any]]:
        query = """
        SELECT f.*, r.payload_json, r.validation_json
        FROM forms f
        JOIN results r ON r.stream_key=f.stream_key AND r.version=f.version
        WHERE f.stream_key=?
        """
        params: list[Any] = [stream_key]
        if before_version is not None:
            query += " AND f.version < ?"
            params.append(before_version)
        query += " ORDER BY f.version ASC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def review_queue(self) -> list[dict[str, Any]]:
        query = """
        SELECT f.*, r.payload_json, r.validation_json,
               (SELECT COUNT(*) FROM review_entries re
                WHERE re.stream_key=f.stream_key AND re.version=f.version) AS review_count
        FROM forms f
        LEFT JOIN results r ON r.stream_key=f.stream_key AND r.version=f.version
        WHERE f.state IN ('ARCHIVED','EXTRACTED','QUARANTINED','CONFLICTED')
        ORDER BY f.discovered_at ASC
        """
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    def add_anomaly(
        self, stream_key: str, code: str, severity: str, message: str, form_url: str | None
    ) -> None:
        with self.connection() as conn:
            exists = conn.execute(
                """SELECT 1 FROM anomalies WHERE stream_key=? AND code=? AND message=? LIMIT 1""",
                (stream_key, code, message),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO anomalies(at,stream_key,code,severity,message,form_url) VALUES(?,?,?,?,?,?)",
                    (utc_now_iso(), stream_key, code, severity, message, form_url),
                )

    def anomaly_feed(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT at,stream_key,code,severity,message,form_url FROM anomalies ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_correction(self, correction: dict[str, Any]) -> None:
        before = json.dumps(correction.get("from"), sort_keys=True)
        after = json.dumps(correction.get("to"), sort_keys=True)
        with self.connection() as conn:
            exists = conn.execute(
                """SELECT 1 FROM corrections
                   WHERE stream_key=? AND field=? AND from_value=? AND to_value=?
                     AND COALESCE(new_form_url,'')=COALESCE(?, '') LIMIT 1""",
                (
                    correction["stream_key"],
                    correction["field"],
                    before,
                    after,
                    correction.get("new_form_url"),
                ),
            ).fetchone()
            if exists:
                return
            conn.execute(
                """
                INSERT INTO corrections(at,stream_key,field,from_value,to_value,reason,prior_form_url,new_form_url)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    correction.get("at", utc_now_iso()),
                    correction["stream_key"],
                    correction["field"],
                    before,
                    after,
                    correction["reason"],
                    correction.get("prior_form_url"),
                    correction.get("new_form_url"),
                ),
            )

    def corrections(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM corrections ORDER BY id ASC").fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["from"] = json.loads(item.pop("from_value"))
            item["to"] = json.loads(item.pop("to_value"))
            item.pop("id", None)
            output.append(item)
        return output

    def heartbeat(self, worker_id: str, status: str, details: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO heartbeats(worker_id,at,status,details_json) VALUES(?,?,?,?)
                ON CONFLICT(worker_id) DO UPDATE SET
                  at=excluded.at,status=excluded.status,details_json=excluded.details_json
                """,
                (worker_id, utc_now_iso(), status, json.dumps(details)),
            )

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_metadata(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO metadata(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
