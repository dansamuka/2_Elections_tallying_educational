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
from .historical_ocr import inventory_documents, run_historical_ocr, tesseract_install_hint
from .historical_sync import load_sync_plan, sync_elections
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

    archive_documents = sub.add_parser(
        "archive-documents", help="Inventory every PDF/image available for a historical election"
    )
    archive_documents.add_argument("election_id")
    archive_documents.add_argument(
        "--include", action="append", default=[], help="Additional file or directory to scan"
    )
    archive_documents.set_defaults(_archive_command=True)

    archive_ocr = sub.add_parser(
        "archive-ocr", help="OCR all historical-election documents into a human review queue"
    )
    archive_ocr.add_argument("election_id")
    archive_ocr.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "embedded", "tesseract", "gcv", "textract", "dual-cloud"],
    )
    archive_ocr.add_argument(
        "--include", action="append", default=[], help="Additional file or directory to scan"
    )
    archive_ocr.add_argument("--rebuild", action="store_true", help="Re-run existing extraction records")
    archive_ocr.set_defaults(_archive_command=True)

    archive_sync = sub.add_parser(
        "archive-sync",
        help="Check the IEBC portal, download new forms, run OCR, and rebuild the archive dashboard",
    )
    archive_sync.add_argument("election_id", nargs="?", help="Election id, or omit with --all")
    archive_sync.add_argument("--all", action="store_true", help="Sync every election enabled in data/elections/sync.json")
    archive_sync.add_argument(
        "--engine",
        default=None,
        choices=["auto", "embedded", "tesseract", "gcv", "textract", "dual-cloud"],
    )
    archive_sync.add_argument("--rebuild", action="store_true", help="Re-run existing OCR extraction records")
    archive_sync.add_argument("--links-only", action="store_true", help="Discover links without downloading or OCR")

    sub.add_parser("ocr-doctor", help="Report local OCR capability and install hints")
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

    if args.command == "ocr-doctor":
        print(json.dumps(tesseract_install_hint(), indent=2))
        return

    if args.command == "archive-sync":
        plan = load_sync_plan(settings.root)
        if args.all:
            election_ids = list(plan.election_ids)
        elif args.election_id:
            election_ids = [args.election_id]
        else:
            raise SystemExit("archive-sync requires an election_id or --all")
        result = sync_elections(
            settings,
            election_ids,
            engine_mode=args.engine or plan.engine,
            rebuild=args.rebuild,
            links_only=args.links_only,
        )
        print(json.dumps(result, indent=2))
        raise SystemExit(2 if result["failures"] else 0)

    if args.command in {
        "archive-build",
        "archive-import",
        "archive-run",
        "archive-documents",
        "archive-ocr",
    }:
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
        if args.command == "archive-documents":
            include = [Path(value) for value in args.include]
            inventory = inventory_documents(bundle, include)
            print(json.dumps(inventory, indent=2))
            return
        if args.command == "archive-ocr":
            include = [Path(value) for value in args.include]
            summary = run_historical_ocr(
                bundle,
                settings,
                engine_mode=args.engine,
                extra_paths=include,
                rebuild=args.rebuild,
            )
            payload = build_archive_payload(bundle)
            build_catalog(settings.root)
            print(json.dumps({"ocr": summary, "coverage": payload["coverage"]}, indent=2))
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
