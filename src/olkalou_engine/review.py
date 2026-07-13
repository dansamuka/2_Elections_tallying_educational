from __future__ import annotations

import json
from dataclasses import dataclass

from .corrections import result_deltas
from .db import EngineDB
from .models import (
    ReviewEntry,
    StreamReference,
    StreamResult,
    TrustState,
    VerificationType,
)
from .validation import Validator


@dataclass(frozen=True)
class ReviewOutcome:
    status: str
    review_count: int
    message: str
    result: StreamResult | None = None


def entries_match(left: ReviewEntry, right: ReviewEntry) -> bool:
    return (
        left.votes == right.votes
        and left.rejected == right.rejected
        and left.registered_form == right.registered_form
        and left.po_total_valid == right.po_total_valid
        and left.total_cast_form == right.total_cast_form
    )


def _payload(entry: ReviewEntry, form_row: dict) -> StreamResult:
    return StreamResult(
        stream_key=entry.stream_key,
        form_version=entry.form_version,
        registered_form=entry.registered_form,
        votes=entry.votes,
        rejected=entry.rejected,
        po_total_valid=entry.po_total_valid,
        total_cast_form=entry.total_cast_form,
        field_confidence={
            key: 1.0 for key in [*entry.votes, "rejected", "registered", "total_valid", "total_cast"]
        },
        engine_agreement=False,
        words_agreement=False,
        form_url=form_row["public_url"],
        source_url=form_row["source_url"],
        sha256=form_row["sha256"],
    )


def _prior_results(db: EngineDB, stream_key: str, version: int) -> list[StreamResult]:
    prior: list[StreamResult] = []
    for row in db.stream_results(stream_key, before_version=version):
        if row.get("payload_json"):
            prior.append(StreamResult.model_validate(json.loads(row["payload_json"])))
    return prior


def _save_checked_result(
    *,
    db: EngineDB,
    payload: StreamResult,
    reference: StreamReference,
    validator: Validator,
    allow_disputed: bool,
) -> tuple[TrustState, str]:
    prior_results = _prior_results(db, payload.stream_key, payload.form_version)
    report = validator.validate(
        payload,
        reference,
        prior_versions=prior_results,
    )
    if prior_results:
        for correction in result_deltas(
            prior_results[-1], payload, reason="Human review of a newer IEBC form version."
        ):
            db.add_correction(correction)
    db.save_result(
        payload.stream_key,
        payload.form_version,
        payload.model_dump(mode="json"),
        report.model_dump(mode="json"),
    )
    for check in report.checks:
        if check.status.value in {"FAIL", "WARN"}:
            db.add_anomaly(
                payload.stream_key,
                check.code,
                check.severity.value,
                check.message,
                payload.form_url,
            )

    if report.has_critical_failure:
        if allow_disputed:
            db.update_form_state(
                payload.stream_key,
                payload.form_version,
                TrustState.DISPUTED,
                VerificationType.DISPUTED.value,
            )
            return TrustState.DISPUTED, "Adjudicated figures published as DISPUTED with failed checks visible."
        db.update_form_state(
            payload.stream_key,
            payload.form_version,
            TrustState.QUARANTINED,
            VerificationType.HUMAN.value,
        )
        return TrustState.QUARANTINED, (
            "Two entries match, but a critical statutory check failed. The stream remains quarantined "
            "until explicit adjudication."
        )

    db.update_form_state(
        payload.stream_key,
        payload.form_version,
        TrustState.PUBLISHED,
        VerificationType.HUMAN.value,
    )
    return TrustState.PUBLISHED, "Two independent entries match and all critical checks pass."


def submit_review(
    db: EngineDB,
    entry: ReviewEntry,
    form_row: dict,
    *,
    reference: StreamReference,
    validator: Validator,
) -> ReviewOutcome:
    db.add_review(entry)
    entries = db.reviews_for(entry.stream_key, entry.form_version)
    if len(entries) < 2:
        return ReviewOutcome("PENDING_SECOND_ENTRY", len(entries), "First independent entry saved.")

    first, second = entries[-2], entries[-1]
    if first.reviewer_id == second.reviewer_id:
        return ReviewOutcome(
            "PENDING_INDEPENDENT_REVIEWER",
            len(entries),
            "A second, different reviewer is required.",
        )
    if not entries_match(first, second):
        db.update_form_state(entry.stream_key, entry.form_version, TrustState.CONFLICTED)
        db.add_anomaly(
            entry.stream_key,
            "DOUBLE_ENTRY_MISMATCH",
            "CRITICAL",
            f"Independent entries by {first.reviewer_id} and {second.reviewer_id} differ.",
            form_row.get("public_url"),
        )
        return ReviewOutcome(
            "MISMATCH",
            len(entries),
            "Independent entries differ. Third-person adjudication is required.",
        )

    payload = _payload(entry, form_row)
    state, message = _save_checked_result(
        db=db,
        payload=payload,
        reference=reference,
        validator=validator,
        allow_disputed=False,
    )
    return ReviewOutcome(state.value, len(entries), message, result=payload)


def adjudicate(
    db: EngineDB,
    entry: ReviewEntry,
    form_row: dict,
    *,
    reference: StreamReference,
    validator: Validator,
) -> ReviewOutcome:
    payload = _payload(entry, form_row)
    db.add_review(entry)
    state, message = _save_checked_result(
        db=db,
        payload=payload,
        reference=reference,
        validator=validator,
        allow_disputed=True,
    )
    return ReviewOutcome(
        "PUBLISHED_AFTER_ADJUDICATION" if state == TrustState.PUBLISHED else "DISPUTED_AFTER_ADJUDICATION",
        len(db.reviews_for(entry.stream_key, entry.form_version)),
        message,
        result=payload,
    )
