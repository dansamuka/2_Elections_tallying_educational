from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import uvicorn

from .archive import (
    build_archive_payload,
    build_catalog,
    import_verified_results,
    load_historical_bundle,
    run_historical_archive,
)
from .config import Settings
from .db import EngineDB
from .publisher import Publisher
from .reconciliation import reconcile, render_markdown
from .reference import load_reference
from .review_api import create_app
from .storage import build_store
from .worker import Worker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="olkalou")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-reference", help="Validate candidates.json and streams.json")
    publish = sub.add_parser("publish", help="Build and publish live.json from current state")
    publish.add_argument("--simulations", type=int, default=1000)

    sub.add_parser("worker", help="Run the 60-second portal watcher and archiver")
    sub.add_parser("tick", help="Run one watcher cycle")

    review = sub.add_parser("review", help="Run the human review console")
    review.add_argument("--host", default=None)
    review.add_argument("--port", type=int, default=None)

    serve = sub.add_parser("serve-static", help="Serve frontend and local public files")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    rec = sub.add_parser("reconcile", help="Create RECONCILIATION.md from Form 35B totals JSON")
    rec.add_argument("form35b_json", type=Path)
    rec.add_argument("--output", type=Path, default=Path("RECONCILIATION.md"))

    archive_list = sub.add_parser("archive-list", help="List configured historical elections")
    archive_list.set_defaults(_archive_command=True)

    archive_build = sub.add_parser("archive-build", help="Build a historical-election website payload")
    archive_build.add_argument("election_id")
    archive_build.set_defaults(_archive_command=True)

    archive_import = sub.add_parser("archive-import", help="Import verified stream results CSV")
    archive_import.add_argument("election_id")
    archive_import.add_argument("results_csv", type=Path)
    archive_import.set_defaults(_archive_command=True)

    archive_run = sub.add_parser("archive-run", help="Discover and archive IEBC forms for a past election")
    archive_run.add_argument("election_id")
    archive_run.add_argument("--links-only", action="store_true", help="Discover links without downloading scans")
    archive_run.set_defaults(_archive_command=True)
    return parser


def settings_for_root(root: str) -> Settings:
    os.environ["ENGINE_ROOT"] = str(Path(root).resolve())
    return Settings()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    settings = settings_for_root(args.root)

    if args.command == "archive-list":
        catalog = build_catalog(settings.root)
        print(json.dumps(catalog, indent=2))
        return

    if args.command in {"archive-build", "archive-import", "archive-run"}:
        bundle = load_historical_bundle(settings.root, args.election_id)
        if args.command == "archive-import":
            csv_path = args.results_csv if args.results_csv.is_absolute() else settings.root / args.results_csv
            imported = import_verified_results(bundle, csv_path)
            payload = build_archive_payload(bundle)
            build_catalog(settings.root)
            print(json.dumps({"imported": len(imported["results"]), "coverage": payload["coverage"]}, indent=2))
            return
        if args.command == "archive-run":
            try:
                result = run_historical_archive(
                    bundle, user_agent=settings.portal_user_agent, download=not args.links_only
                )
            except Exception as exc:
                print(json.dumps({
                    "election_id": args.election_id,
                    "status": "ERROR",
                    "message": str(exc),
                    "hint": "Check internet access and the configured IEBC portal URL, then retry.",
                }, indent=2))
                raise SystemExit(2) from None
            build_catalog(settings.root)
            print(json.dumps(result, indent=2))
            return
        payload = build_archive_payload(bundle)
        build_catalog(settings.root)
        print(json.dumps({"election_id": args.election_id, "coverage": payload["coverage"], "archive": payload["archive"]}, indent=2))
        return

    reference = load_reference(settings.candidates_path, settings.streams_path)

    if args.command == "check-reference":
        errors = reference.production_errors()
        print(json.dumps({"complete": reference.complete, "errors": errors}, indent=2))
        raise SystemExit(1 if errors else 0)

    if args.command == "publish":
        publisher = Publisher(
            settings=settings,
            db=EngineDB(settings.db_path),
            reference=reference,
            store=build_store(settings),
        )
        payload = publisher.publish(simulations=args.simulations)
        print(json.dumps({"seq": payload["seq"], "coverage": payload["coverage"]}, indent=2))
        return

    if args.command in {"worker", "tick"}:
        worker = Worker(settings)
        if args.command == "worker":
            worker.run_forever()
        else:
            try:
                print(json.dumps(worker.tick(), indent=2))
            finally:
                worker.close()
        return

    if args.command == "review":
        app = create_app(settings)
        uvicorn.run(app, host=args.host or settings.review_host, port=args.port or settings.review_port)
        return

    if args.command == "serve-static":
        from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

        os.chdir(settings.root)
        server = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
        print(f"Static server: http://{args.host}:{args.port}/frontend/")
        server.serve_forever()
        return

    if args.command == "reconcile":
        live = json.loads(settings.live_path.read_text(encoding="utf-8"))
        totals35a = {row["id"]: row["votes"] for row in live["candidates"]}
        totals35b = json.loads(args.form35b_json.read_text(encoding="utf-8"))
        names = {candidate.id: candidate.name for candidate in reference.candidates.candidates}
        report = reconcile(names, totals35a, totals35b)
        output = settings.path(args.output)
        render_markdown(report, output)
        print(output)
        return


if __name__ == "__main__":
    main()
