from __future__ import annotations

from typing import Any

from .models import StreamResult, utc_now_iso


def result_deltas(previous: StreamResult, current: StreamResult, *, reason: str) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    fields: list[tuple[str, Any, Any]] = []
    for candidate_id in sorted(set(previous.votes) | set(current.votes)):
        fields.append(
            (
                f"candidate_{candidate_id}",
                previous.votes.get(candidate_id, 0),
                current.votes.get(candidate_id, 0),
            )
        )
    fields.extend(
        [
            ("rejected", previous.rejected, current.rejected),
            ("registered_form", previous.registered_form, current.registered_form),
            ("po_total_valid", previous.po_total_valid, current.po_total_valid),
            ("total_cast_form", previous.total_cast_form, current.total_cast_form),
        ]
    )
    for field, before, after in fields:
        if before != after:
            deltas.append(
                {
                    "at": utc_now_iso(),
                    "stream_key": current.stream_key,
                    "field": field,
                    "from": before,
                    "to": after,
                    "reason": reason,
                    "prior_form_url": previous.form_url,
                    "new_form_url": current.form_url,
                }
            )
    return deltas
