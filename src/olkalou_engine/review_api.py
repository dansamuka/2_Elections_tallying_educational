from __future__ import annotations

import json
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, get_settings
from .db import EngineDB
from .models import ReviewEntry
from .publisher import Publisher
from .reference import load_reference
from .review import adjudicate, submit_review
from .storage import build_store
from .validation import Validator


class ReviewRequest(BaseModel):
    reviewer_id: str
    votes: dict[str, int]
    rejected: int
    registered_form: int
    po_total_valid: int
    total_cast_form: int
    notes: str | None = None


class AdjudicationRequest(ReviewRequest):
    confirmation: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.review_api_token == "change-me":
        # SECURITY FIX (13 Jul 2026 audit): this used to silently disable
        # auth entirely whenever the token was left at its default. Combined
        # with REVIEW_HOST defaulting to 0.0.0.0 (all interfaces) and CORS
        # allow_origins=["*"], an operator who forgot to set
        # REVIEW_API_TOKEN would unknowingly run a review console -- which
        # can publish election results -- open to anyone on the network
        # with zero authentication. Refuse to start instead of failing open.
        raise RuntimeError(
            "REVIEW_API_TOKEN is still the default 'change-me'. Set a real, "
            "unique token via the REVIEW_API_TOKEN environment variable "
            "before starting the review console -- this is not optional, "
            "the console can publish election results. See .env.example."
        )
    db = EngineDB(settings.db_path)
    reference = load_reference(settings.candidates_path, settings.streams_path)
    publisher = Publisher(
        settings=settings,
        db=db,
        reference=reference,
        store=build_store(settings),
    )
    validator = Validator(
        confidence_threshold=settings.machine_confidence_threshold,
        rejected_rate_low=settings.rejected_rate_low,
        rejected_rate_high=settings.rejected_rate_high,
    )
    streams_by_key = {stream.stream_key: stream for stream in reference.streams.streams}
    app = FastAPI(title="Ol Kalou Review Console", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def require_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        # No default-token bypass here: create_app() above already refuses
        # to start with the default token, so `expected` is always an
        # operator-chosen value by the time this runs, and must always be
        # checked -- no early return.
        expected = settings.review_api_token
        if authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="Invalid review API token")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "OK",
            "reference_complete": reference.complete,
            "reference_errors": reference.production_errors(),
        }

    @app.get("/api/reference", dependencies=[Depends(require_token)])
    def get_reference() -> dict:
        return {
            "candidates": reference.candidates.model_dump(mode="json"),
            "streams": reference.streams.model_dump(mode="json"),
        }

    @app.get("/api/review/queue", dependencies=[Depends(require_token)])
    def queue() -> dict:
        rows = db.review_queue()
        return {
            "count": len(rows),
            "items": [serialize_queue_item(row) for row in rows],
        }

    @app.get("/api/provisional", dependencies=[Depends(require_token)])
    def provisional() -> dict:
        # Internal QA tool only -- see provisional.py module docstring for
        # why this is authenticated-only and never touches data/public/.
        from .provisional import build_provisional

        return build_provisional(db, reference)

    @app.get("/api/historical-provisional/{election_id}", dependencies=[Depends(require_token)])
    def historical_provisional(election_id: str) -> dict:
        # Same authenticated, internal-only scoping as /api/provisional, for
        # historical elections (Banissa etc.) -- see
        # historical_provisional.py module docstring.
        from .archive import load_historical_bundle
        from .historical_provisional import build_historical_provisional

        try:
            bundle = load_historical_bundle(settings.root, election_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return build_historical_provisional(bundle)

    @app.get("/api/review/{stream_key}/{version}", dependencies=[Depends(require_token)])
    def review_item(stream_key: str, version: int) -> dict:
        row = db.get_form(stream_key, version)
        if not row:
            raise HTTPException(status_code=404, detail="Form version not found")
        payload = _json(row.get("payload_json"))
        validation = _json(row.get("validation_json"))
        stream = next((s for s in reference.streams.streams if s.stream_key == stream_key), None)
        return {
            "form": serialize_queue_item(row),
            "stream": stream.model_dump(mode="json") if stream else None,
            "prefill": payload,
            "validation": validation,
            "reviews": [entry.model_dump(mode="json") for entry in db.reviews_for(stream_key, version)],
        }

    @app.post("/api/review/{stream_key}/{version}", dependencies=[Depends(require_token)])
    def post_review(stream_key: str, version: int, request: ReviewRequest) -> dict:
        row = db.get_form(stream_key, version)
        if not row:
            raise HTTPException(status_code=404, detail="Form version not found")
        candidate_ids = {candidate.id for candidate in reference.candidates.candidates}
        if set(request.votes) != candidate_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Votes must contain exactly these candidate ids: {sorted(candidate_ids)}",
            )
        entry = ReviewEntry(
            stream_key=stream_key,
            form_version=version,
            **request.model_dump(),
        )
        stream_reference = streams_by_key.get(stream_key)
        if stream_reference is None or stream_reference.registered is None:
            raise HTTPException(status_code=409, detail="Certified stream reference is unresolved; review cannot publish.")
        outcome = submit_review(
            db, entry, row, reference=stream_reference, validator=validator
        )
        if outcome.result:
            publisher.publish(simulations=500)
        return {
            "status": outcome.status,
            "review_count": outcome.review_count,
            "message": outcome.message,
        }

    @app.post("/api/adjudicate/{stream_key}/{version}", dependencies=[Depends(require_token)])
    def post_adjudication(stream_key: str, version: int, request: AdjudicationRequest) -> dict:
        if request.confirmation != "I VERIFIED THE SOURCE FORM":
            raise HTTPException(status_code=422, detail="Explicit confirmation phrase is required")
        row = db.get_form(stream_key, version)
        if not row:
            raise HTTPException(status_code=404, detail="Form version not found")
        entry = ReviewEntry(
            stream_key=stream_key,
            form_version=version,
            **request.model_dump(exclude={"confirmation"}),
        )
        stream_reference = streams_by_key.get(stream_key)
        if stream_reference is None or stream_reference.registered is None:
            raise HTTPException(status_code=409, detail="Certified stream reference is unresolved; adjudication cannot publish.")
        outcome = adjudicate(
            db, entry, row, reference=stream_reference, validator=validator
        )
        publisher.publish(simulations=500)
        return {
            "status": outcome.status,
            "review_count": outcome.review_count,
            "message": outcome.message,
        }

    raw_mount = settings.raw_dir
    raw_mount.mkdir(parents=True, exist_ok=True)
    app.mount("/raw-local", StaticFiles(directory=raw_mount), name="raw-local")
    console_dir = settings.path("review_console")
    app.mount("/assets", StaticFiles(directory=console_dir), name="review-assets")

    @app.get("/")
    def console() -> FileResponse:
        return FileResponse(console_dir / "index.html")

    return app


def _json(value: str | None):
    return json.loads(value) if value else None


def serialize_queue_item(row: dict) -> dict:
    public_url = row.get("public_url")
    if public_url and "/data/public/raw/" in public_url:
        # Review server exposes the local archive directly even when the static server is absent.
        public_url = "/raw-local/" + public_url.split("/data/public/raw/", 1)[1]
    return {
        "stream_key": row["stream_key"],
        "version": row["version"],
        "state": row["state"],
        "verification": row.get("verification"),
        "form_type": row.get("form_type"),
        "form_url": public_url,
        "source_url": row.get("source_url"),
        "sha256": row.get("sha256"),
        "discovered_at": row.get("discovered_at"),
        "review_count": row.get("review_count", 0),
    }

# NOTE: no module-level `app = create_app()` here on purpose. Every actual
# entrypoint (docker-compose's `review` service, deploy/systemd, and
# `cli.py`'s `review` subcommand) calls create_app(settings) explicitly with
# real settings resolved from the environment. A module-level call here
# would run at *import* time with whatever default settings happen to be
# present -- which is exactly the footgun that let the auth-bypass bug (see
# the fix above) go unnoticed: the app instance existed and was importable
# with a default/insecure token before anyone had a chance to configure one.
