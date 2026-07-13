"""Provisional (unverified) OCR aggregate for HISTORICAL elections (Banissa,
and any future one added under data/elections/<id>/) -- the file-based
counterpart to provisional.py, which serves the live Ol Kalou / EngineDB
pipeline. Same purpose, same internal-only scoping, different storage
backend (JSON files under ocr/extractions/, not SQLite).

WHY THIS EXISTS: as an operator QA signal -- same as provisional.py.

WHY IT'S DIFFERENT FROM OL KALOU'S RISK PROFILE, NOT LOWER-STAKES: Banissa's
election is over and officially gazetted (Hassan Ahmed Maalim / UDA,
10,431 votes -- data/elections/banissa-2025/election.json). There's no
"who's ahead" narrative this can prematurely feed. But there's a different,
still-real risk: this repo's whole historical module exists to
independently RECONCILE scanned Form 35A sums against that declaration
(build_archive_payload's "replay", gated off until verified -- see
election.json's methodology.replay_available). A raw, error-prone OCR sum
that happens to disagree with the certified 10,431 is exactly the kind of
thing that gets misread as "evidence the declared result was wrong" when
it's actually just a misread digit on one form. That's a real harm too --
undermining confidence in an already-certified, legitimate result -- just a
different one than Ol Kalou's live-count risk. Same conclusion either way:
keep it internal, labelled, and separate from anything public.

WHY IT IS NOT IN the public archive payload: build_archive_payload()
(archive.py) already keeps this exact separation -- ocr_by_stream is loaded
and used for STATUS ("this stream shows OCR_REVIEW") but its vote VALUES
never reach candidate_totals or a stream's public "votes" field; only
verified_results.json (human-reviewed, statutory-checks-passed,
import_verified_results()) does. This module deliberately does not change
that. It reads the same ocr/extractions/*.json files purely to produce an
operator-facing sum, and is never called from archive.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .archive import HistoricalBundle
from .historical_ocr import load_ocr_stream_extractions
from .models import utc_now_iso

WARNING = (
    "NOT A CERTIFIED RESULT. Raw, unweighted sum of whatever OCR has "
    "extracted from scanned forms so far, INCLUDING forms that failed "
    "statutory checks or have not been independently reviewed. For a "
    "completed, already-gazetted election, a mismatch against the "
    "official declaration here usually means an OCR misread on ONE form, "
    "not a problem with the certified result. Do not screenshot, quote, or "
    "share this outside the operator team -- treat it as a reconciliation "
    "QA signal, not a finding."
)


def _load_verified_results(bundle: HistoricalBundle) -> dict[str, dict[str, Any]]:
    """Same file archive.py's import_verified_results() writes
    (verified_results.json) -- reading it locally rather than importing
    archive.py's private _load_results() keeps this module decoupled from
    archive.py's internals."""
    path = bundle.verified_results_path
    if not path.exists():
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(row["stream_key"]): row for row in doc.get("results", [])}


def build_historical_provisional(bundle: HistoricalBundle) -> dict[str, Any]:
    candidate_ids = [str(c["id"]) for c in bundle.candidates]
    candidate_lookup = {str(c["id"]): c for c in bundle.candidates}
    stream_ref = {str(s["stream_key"]): s for s in bundle.streams}

    verified = _load_verified_results(bundle)  # stream_key -> verified row (already human-checked)
    ocr_by_stream = load_ocr_stream_extractions(bundle)  # stream_key -> best OCR extraction

    candidate_totals = {cid: 0 for cid in candidate_ids}
    contributing: list[dict[str, Any]] = []
    source_breakdown = {"VERIFIED": 0, "OCR_ONLY": 0}

    for stream_key in stream_ref:
        verified_row = verified.get(stream_key)
        if verified_row is not None:
            votes = {cid: int(verified_row["votes"].get(cid, 0)) for cid in candidate_ids}
            source = "VERIFIED"
        else:
            ocr_row = ocr_by_stream.get(stream_key)
            if ocr_row is None:
                continue  # nothing extracted for this stream yet
            fields = (ocr_row.get("parsed") or {}).get("fields", {})
            raw_votes = {cid: fields.get(f"candidate_{cid}", {}).get("value") for cid in candidate_ids}
            if all(v is None for v in raw_votes.values()):
                continue  # extraction ran but found no candidate figures on this page
            votes = {cid: int(v) for cid, v in raw_votes.items() if v is not None}
            source = "OCR_ONLY"

        for cid, v in votes.items():
            candidate_totals[cid] += v
        source_breakdown[source] += 1

        contributing.append({
            "stream_key": stream_key,
            "ward": stream_ref[stream_key].get("ward_name"),
            "source": source,
            "votes": votes,
        })

    valid_total = sum(candidate_totals.values())
    candidate_rows = sorted(
        (
            {
                "id": cid,
                "name": candidate_lookup[cid]["name"],
                "party": candidate_lookup[cid]["party"],
                "votes": candidate_totals[cid],
                "share": (candidate_totals[cid] / valid_total) if valid_total else 0.0,
            }
            for cid in candidate_ids
        ),
        key=lambda r: -r["votes"],
    )

    official = bundle.profile.get("official_declaration", {}) or {}
    official_totals = official.get("candidate_totals") or {}

    return {
        "schema": "kenya.election.historical-provisional.v1",
        "PROVISIONAL_UNVERIFIED": True,
        "warning": WARNING,
        "election_id": bundle.election_id,
        "generated_at": utc_now_iso(),
        "streams_contributing": len(contributing),
        "streams_total": len(bundle.streams),
        "source_breakdown": source_breakdown,
        "candidates": candidate_rows,
        "valid_votes": valid_total,
        "official_declaration_for_reference": {
            "candidate_totals": official_totals,
            "valid_votes": official.get("valid_votes"),
            "note": (
                "Shown for QA comparison only -- this is the certified Gazette "
                "figure, not derived from the sum above. A difference between "
                "the two is a reconciliation lead, not a correction to either."
            ),
        } if official_totals else None,
        "contributing_streams": sorted(contributing, key=lambda r: r["stream_key"]),
    }
