from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def local_form_path(site_root: Path, value: str) -> Path | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return None
    raw = parsed.path.replace("\\", "/")
    while raw.startswith("../"):
        raw = raw[3:]
    if raw.startswith("./"):
        raw = raw[2:]
    return site_root / raw


def validate(site_root: Path) -> list[str]:
    failures: list[str] = []
    elections = site_root / "data" / "public" / "elections"
    for payload_path in sorted(elections.glob("*.json")):
        if payload_path.name == "catalog.json":
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"{payload_path}: invalid JSON: {exc}")
            continue
        for stream in payload.get("streams", []):
            form_url = str(stream.get("form_url") or "")
            local = local_form_path(site_root, form_url)
            if local is not None and not local.is_file():
                failures.append(
                    f"{payload.get('election_id')} {stream.get('stream_key')}: "
                    f"missing local form target {form_url} -> {local.relative_to(site_root)}"
                )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-root", type=Path, required=True)
    args = parser.parse_args()
    failures = validate(args.site_root)
    if failures:
        for failure in failures[:100]:
            print(f"ERROR: {failure}")
        raise SystemExit(f"{len(failures)} broken archived Form 35A link(s)")
    print("Archived Form 35A links validated.")


if __name__ == "__main__":
    main()
