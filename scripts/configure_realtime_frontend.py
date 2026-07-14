from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write frontend/config.js for the always-on realtime API and optional R2 data origin."
    )
    parser.add_argument("--api-base", required=True, help="HTTPS realtime API or Cloudflare Worker origin")
    parser.add_argument(
        "--data-base",
        default="",
        help="Optional public R2/custom-domain prefix containing live.json and elections/",
    )
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    api = args.api_base.rstrip("/")
    data = args.data_base.rstrip("/")
    config = {
        "realtimeApiBase": api,
        "liveDataBaseUrls": [data] if data else [],
        "archiveDataBaseUrls": [data] if data else [],
        "liveUrls": ["../data/public/live.json"],
        "refreshMs": 5000,
        "refreshWatchMs": 2000,
        "refreshWatchTimeoutMs": 90000,
        "refreshTriggersSyncWhenAuthorized": True,
        "ownerTokenSessionKey": "olkalou.realtime.ownerToken",
        "archiveCatalogUrl": "../data/public/elections/catalog.json",
        "archiveUpdateWorkflowUrl": "https://github.com/dansamuka/2_Elections_tallying_educational/actions/workflows/sync-historical-forms.yml",
        "archiveSyncMinutes": 5,
        "liveElectionId": "ol-kalou-2026",
    }
    path = Path(args.root).resolve() / "frontend" / "config.js"
    path.write_text(
        "window.OLKALOU_CONFIG = " + json.dumps(config, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(path)


if __name__ == "__main__":
    main()
