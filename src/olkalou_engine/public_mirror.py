from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import ObjectStore, build_store


class PublicDataMirror:
    """Publish small current-state JSON separately from GitHub Pages deployment.

    When S3/R2 settings are present this writes directly to the object store. With no
    bucket configured it atomically writes under ``data/public`` so local and Docker
    deployments use the exact same code path.
    """

    def __init__(self, settings: Settings, store: ObjectStore | None = None):
        self.settings = settings
        self.store = store or build_store(settings)
        self.root = settings.root
        self.cache_control = "public,max-age=2,must-revalidate"

    def publish_election(self, election_id: str) -> dict[str, Any]:
        path = self.root / "data" / "public" / "elections" / f"{election_id}.json"
        payload = self._read(path)
        self.store.put_json(f"elections/{election_id}.json", payload, self.cache_control)
        return payload

    def publish_catalog(self) -> dict[str, Any]:
        path = self.root / "data" / "public" / "elections" / "catalog.json"
        payload = self._read(path)
        self.store.put_json("elections/catalog.json", payload, self.cache_control)
        return payload

    def publish_live(self) -> dict[str, Any]:
        path = self.settings.live_path
        payload = self._read(path)
        self.store.put_json("live.json", payload, self.cache_control)
        return payload

    def publish_status(self, election_id: str, status: dict[str, Any]) -> str:
        return self.store.put_json(
            f"realtime/status/{election_id}.json",
            status,
            "public,max-age=1,must-revalidate",
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))
