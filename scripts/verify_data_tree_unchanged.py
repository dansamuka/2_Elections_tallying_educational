from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "kenya.election.data-tree-snapshot.v1"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_snapshot(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
        relative = path.relative_to(resolved).as_posix()
        files[relative] = {
            "sha256": _hash_file(path),
            "size": path.stat().st_size,
        }
    return {"schema": SCHEMA, "root": str(resolved), "files": files}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or not isinstance(value.get("files"), dict):
        raise ValueError(f"Unsupported or malformed snapshot: {path}")
    return value


def compare_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    before_files = before["files"]
    after_files = after["files"]
    before_names = set(before_files)
    after_names = set(after_files)
    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)
    changed = [
        {
            "path": name,
            "before": before_files[name],
            "after": after_files[name],
        }
        for name in sorted(before_names & after_names)
        if before_files[name] != after_files[name]
    ]
    return {
        "schema": "kenya.election.data-tree-diff.v1",
        "unchanged": not added and not removed and not changed,
        "added": added,
        "removed": removed,
        "changed": changed,
        "before_file_count": len(before_files),
        "after_file_count": len(after_files),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)

    compare = sub.add_parser("compare")
    compare.add_argument("--root", type=Path, required=True)
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "snapshot":
        snapshot = build_snapshot(args.root)
        write_json(args.output, snapshot)
        print(
            json.dumps(
                {"files": len(snapshot["files"]), "output": str(args.output)}
            )
        )
        return 0

    before = load_snapshot(args.before)
    after = build_snapshot(args.root)
    report = compare_snapshots(before, after)
    write_json(args.report, report)
    print(json.dumps(report, indent=2))
    return 0 if report["unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
