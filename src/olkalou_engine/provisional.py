"""Provisional (unverified) OCR aggregate -- an operator/QA tool, NOT a
public output.

Sums candidate votes across every stream that has ANY recorded extraction
result, regardless of trust state -- including QUARANTINED forms that have
not passed statutory validation or independent human review, and even
CONFLICTED forms with disputed figures. This is deliberately the opposite
discipline of Publisher.build() (publisher.py), which only ever counts
PUBLISHED/DISPUTED streams.

WHY THIS EXISTS: as a sanity/QA signal for the people running the pipeline
-- "does raw OCR output look roughly in the right neighbourhood, or is
something badly miscalibrated" -- and as a coverage indicator ("how many
forms has extraction actually touched so far"). That is a legitimate,
narrow use case.

WHY IT IS NOT IN live.json: a raw sum of unverified, uncross-checked OCR
reads is exactly what the rest of this codebase's validation gates (V01-V12,
dual-engine consensus, numerals-vs-words, double-entry review) exist to keep
away from anything published. Every one of this repo's own notes files
repeats the same rule: "OCR remains review-only," "no candidate total is
published until human verification and statutory validation pass." A number
that LOOKS like a result, even captioned "unverified," is a real
misinformation risk once it leaves an authenticated operator tool during a
live, contested election -- screenshots travel without their caption. So:

  - build_provisional() is called ONLY from the authenticated review API
    (review_api.py's /api/provisional, behind the same require_token()
    dependency as everything else) and the `provisional` CLI command
    (operator's own terminal). It is never called from publisher.py, never
    written into anything under data/public/, and never reaches
    live.json or the public dashboard.
  - Every dict this module returns is stamped with an unmissable warning
    string and a PROVISIONAL_UNVERIFIED=True flag, so any code path that
    *does* eventually consume it can't mistake it for a verified payload
    without deliberately ignoring an explicit marker.

If you want this made public, that's a real design decision with real
tradeoffs -- make it deliberately (e.g. a clearly-separate, clearly-labelled
panel on the dashboard, never merged into the candidate totals), not by
piping this function's output into publisher.py.
"""
from __future__ import annotations

import json
from typing import Any

from .db import EngineDB
from .models import utc_now_iso
from .reference import ReferenceBundle

WARNING = (
    "NOT AN ELECTION RESULT. Raw, unweighted sum of whatever OCR has "
    "extracted from every scanned form processed so far, INCLUDING forms "
    "that have failed statutory checks, disagree between engines, or have "
    "not been seen by a human reviewer at all. Do not screenshot, quote, "
    "or share this outside the operator team. It exists to sanity-check "
    "the OCR pipeline, not to indicate who is leading."
)


def _load_json(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


def build_provisional(db: EngineDB, reference: ReferenceBundle) -> dict[str, Any]:
    candidates = reference.candidates.candidates
    stream_ref = {s.stream_key: s for s in reference.streams.streams}
    candidate_totals = {c.id: 0 for c in candidates}

    contributing: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}

    for row in db.current_forms():
        payload = _load_json(row.get("payload_json"))
        if not payload:
            continue  # discovered/archived but no extraction result recorded yet
        votes = {k: int(v) for k, v in (payload.get("votes") or {}).items() if k in candidate_totals}
        if not votes:
            continue

        state = row.get("state", "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1

        for cid, v in votes.items():
            candidate_totals[cid] += v

        ref = stream_ref.get(row["stream_key"])
        contributing.append({
            "stream_key": row["stream_key"],
            "ward": ref.ward_name if ref else None,
            "state": state,
            "verification": row.get("verification", "NONE"),
            "votes": votes,
            "form_url": row.get("public_url"),
        })

    valid_total = sum(candidate_totals.values())
    candidate_rows = sorted(
        (
            {
                "id": c.id,
                "name": c.name,
                "party": c.party,
                "votes": candidate_totals[c.id],
                "share": (candidate_totals[c.id] / valid_total) if valid_total else 0.0,
            }
            for c in candidates
        ),
        key=lambda r: -r["votes"],
    )

    return {
        "schema": "olkalou.provisional.v1",
        "PROVISIONAL_UNVERIFIED": True,
        "warning": WARNING,
        "generated_at": utc_now_iso(),
        "forms_contributing": len(contributing),
        "forms_total": len(reference.streams.streams),
        "included_states": sorted(state_counts.keys()),
        "excluded_note": (
            "Streams with no extraction result yet (AWAITING/DISCOVERED/"
            "ARCHIVED-not-yet-extracted) are simply absent, not zero-filled."
        ),
        "state_breakdown": state_counts,
        "candidates": candidate_rows,
        "valid_votes": valid_total,
        "contributing_streams": sorted(contributing, key=lambda r: r["stream_key"]),
    }


def is_meaningfully_different_from_published(provisional: dict, published_candidates: list[dict]) -> bool:
    """QA helper: flags a large divergence between the provisional (raw OCR)
    leader and the published (verified) leader as worth a human's attention
    -- e.g. to catch a miscalibrated ROI map early. Never used to alter
    what's published; purely an operator signal.
    """
    if not provisional["candidates"] or not published_candidates:
        return False
    prov_leader = provisional["candidates"][0]["id"]
    pub_leader = max(published_candidates, key=lambda c: c["votes"])["id"] if published_candidates else None
    return prov_leader != pub_leader
