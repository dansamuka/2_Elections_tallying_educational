from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from .config import Settings
from .db import EngineDB
from .models import TrustState, utc_now_iso
from .projections import hard_bounds, monte_carlo
from .reference import ReferenceBundle
from .storage import ObjectStore
from .validation import vote_share_outliers


COUNTED_STATES = {TrustState.PUBLISHED.value, TrustState.DISPUTED.value}
EXCLUDED_STATES = {TrustState.DISRUPTED.value, TrustState.POSTPONED.value, TrustState.VOIDED.value}


def _load_json(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


class Publisher:
    def __init__(
        self,
        *,
        settings: Settings,
        db: EngineDB,
        reference: ReferenceBundle,
        store: ObjectStore,
    ):
        self.settings = settings
        self.db = db
        self.reference = reference
        self.store = store
        self.stream_ref = {s.stream_key: s for s in reference.streams.streams}
        self.candidates = reference.candidates.candidates

    def build(self, simulations: int = 1_000) -> dict[str, Any]:
        current = {row["stream_key"]: row for row in self.db.current_forms()}
        candidate_totals = {candidate.id: 0 for candidate in self.candidates}
        stream_payloads: list[dict[str, Any]] = []
        published_for_model: list[dict[str, Any]] = []
        outstanding_for_model: list[dict[str, Any]] = []
        coverage = {
            "streams_total": len(self.reference.streams.streams),
            "published": 0,
            "in_review": 0,
            "conflicted": 0,
            "awaiting": 0,
            "excluded": {"count": 0, "reason": None},
            "registered_total": self.reference.streams.register_total,
            "registered_reported": 0,
            "registered_pct": 0.0,
        }
        valid_votes = rejected_votes = total_cast = 0
        observed_turnouts: list[float] = []
        ward_aggregate: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "streams_total": 0,
                "published": 0,
                "registered": 0,
                "registered_reported": 0,
                "valid": 0,
                "cast": 0,
                "candidates": {candidate.id: 0 for candidate in self.candidates},
            }
        )

        for reference in self.reference.streams.streams:
            ward = ward_aggregate[reference.ward_name]
            ward["streams_total"] += 1
            ward["registered"] += int(reference.registered or 0)
            row = current.get(reference.stream_key)
            if row is None:
                coverage["awaiting"] += 1
                outstanding_for_model.append(reference.model_dump())
                stream_payloads.append(self._awaiting_payload(reference))
                continue

            state = row["state"]
            if state in COUNTED_STATES and row.get("payload_json"):
                payload = _load_json(row["payload_json"]) or {}
                votes = {key: int(value) for key, value in payload.get("votes", {}).items()}
                valid = sum(votes.values())
                rejected = int(payload.get("rejected", 0))
                cast = valid + rejected
                registered = int(reference.registered or 0)
                turnout = cast / registered if registered else None
                for candidate in self.candidates:
                    candidate_totals[candidate.id] += votes.get(candidate.id, 0)
                    ward["candidates"][candidate.id] += votes.get(candidate.id, 0)
                valid_votes += valid
                rejected_votes += rejected
                total_cast += cast
                coverage["published"] += 1
                coverage["registered_reported"] += registered
                ward["published"] += 1
                ward["registered_reported"] += registered
                ward["valid"] += valid
                ward["cast"] += cast
                if turnout is not None:
                    observed_turnouts.append(turnout)
                public = self._published_payload(reference, row, payload, turnout)
                stream_payloads.append(public)
                published_for_model.append(
                    {
                        "stream_key": reference.stream_key,
                        "ward_name": reference.ward_name,
                        "registered": registered,
                        "votes": votes,
                        "turnout": turnout,
                    }
                )
            elif state == TrustState.CONFLICTED.value:
                coverage["conflicted"] += 1
                coverage["in_review"] += 1
                outstanding_for_model.append(reference.model_dump())
                stream_payloads.append(self._state_payload(reference, row, state))
            elif state in EXCLUDED_STATES:
                coverage["excluded"]["count"] += 1
                stream_payloads.append(self._state_payload(reference, row, state))
            else:
                coverage["in_review"] += 1
                outstanding_for_model.append(reference.model_dump())
                stream_payloads.append(self._state_payload(reference, row, state))

        if coverage["registered_total"]:
            coverage["registered_pct"] = coverage["registered_reported"] / coverage["registered_total"]

        candidate_rows: list[dict[str, Any]] = []
        for candidate in sorted(self.candidates, key=lambda c: (-candidate_totals[c.id], c.name)):
            votes = candidate_totals[candidate.id]
            candidate_rows.append(
                {
                    "id": candidate.id,
                    "ballot_no": candidate.ballot_no,
                    "name": candidate.name,
                    "party": candidate.party,
                    "abbr": candidate.abbr,
                    "bloc": candidate.bloc,
                    "colour": candidate.colour,
                    "votes": votes,
                    "share": votes / valid_votes if valid_votes else 0.0,
                    "swing_2022": None,
                }
            )

        blocs: dict[str, dict[str, Any]] = {}
        for bloc_name, parties in self.reference.candidates.blocs.items():
            votes = sum(row["votes"] for row in candidate_rows if row["abbr"] in parties)
            blocs[bloc_name] = {"votes": votes, "share": votes / valid_votes if valid_votes else 0.0}
        blocs["note"] = (
            "Arithmetic aggregation only. Not a prediction of transfer behaviour."
        )

        remaining_registered = sum(int(row.get("registered") or 0) for row in outstanding_for_model)
        projection = hard_bounds(candidate_totals, remaining_registered, observed_turnouts)
        projection["t3_model"] = monte_carlo(
            published=published_for_model,
            outstanding=outstanding_for_model,
            candidate_ids=[candidate.id for candidate in self.candidates],
            simulations=simulations,
            seed=int(time.time()) // 60,
        )

        wards: list[dict[str, Any]] = []
        ward_codes = {
            row["name"]: row.get("code") for row in self.reference.streams.ward_summary
        }
        for name, values in ward_aggregate.items():
            wards.append(
                {
                    "code": ward_codes.get(name),
                    "name": name,
                    "streams_total": values["streams_total"],
                    "published": values["published"],
                    "registered": values["registered"],
                    "registered_reported": values["registered_reported"],
                    "turnout": values["cast"] / values["registered_reported"]
                    if values["registered_reported"]
                    else None,
                    "candidates": values["candidates"],
                }
            )

        self._append_outlier_anomalies(published_for_model, current)
        payload = {
            "schema": "olkalou.live.v2",
            "seq": int(time.time_ns() // 1_000_000),
            "generated_at": utc_now_iso(),
            "election": {
                "constituency": "OL KALOU",
                "code": "091",
                "date": "2026-07-16",
            },
            "status": self._election_status(),
            "reference": {
                "complete": self.reference.complete,
                "errors": self.reference.production_errors(),
                "register_source": self.reference.streams.register_source,
                "candidate_source": self.reference.candidates.source,
            },
            "pipeline_health": {
                "watcher": self.db.get_metadata("watcher_status", "UNKNOWN"),
                "extractor": self.db.get_metadata("extractor_status", "MANUAL_ONLY"),
                "last_portal_ok": self.db.get_metadata("last_portal_ok"),
                "worker_id": self.settings.worker_id,
            },
            "coverage": coverage,
            "totals": {
                "valid_votes": valid_votes,
                "rejected_votes": rejected_votes,
                "total_cast": total_cast,
                "turnout_of_reported": total_cast / coverage["registered_reported"]
                if coverage["registered_reported"]
                else 0.0,
            },
            "candidates": candidate_rows,
            "blocs": blocs,
            "projection": projection,
            "wards": sorted(wards, key=lambda row: row["name"]),
            "streams": stream_payloads,
            "anomaly_feed": self.db.anomaly_feed(),
            "corrections": self.db.corrections(),
            "editorial_notice": (
                "UNOFFICIAL — Independent parallel tally compiled from IEBC-published Form 35A scans. "
                "Only the Returning Officer may declare the result of this election."
            ),
        }
        return payload

    def publish(self, simulations: int = 1_000) -> dict[str, Any]:
        payload = self.build(simulations=simulations)
        worker_key = f"workers/{self.settings.worker_id}/live.json"
        current = self.store.get_json(worker_key)
        alias = self.store.get_json("live.json")
        floor = max(
            int(current.get("seq", 0)) if current else 0,
            int(alias.get("seq", 0)) if alias else 0,
        )
        if int(payload["seq"]) <= floor:
            payload["seq"] = floor + 1
        self.store.put_json(worker_key, payload, "public,max-age=20")
        latest_alias = self.store.get_json("live.json")
        if not latest_alias or int(payload["seq"]) > int(latest_alias.get("seq", 0)):
            self.store.put_json("live.json", payload, "public,max-age=20")
        return payload

    def _awaiting_payload(self, reference) -> dict[str, Any]:
        return {
            "stream_key": reference.stream_key,
            "station_name": reference.station_name,
            "stream_no": reference.stream_no,
            "ward": reference.ward_name,
            "state": TrustState.AWAITING.value,
            "verification": "NONE",
            "registered": reference.registered,
            "votes": {},
            "checks": {},
            "form_url": None,
            "form_version": None,
        }

    def _state_payload(self, reference, row: dict[str, Any], state: str) -> dict[str, Any]:
        validation = _load_json(row.get("validation_json")) or {}
        return {
            "stream_key": reference.stream_key,
            "station_name": reference.station_name,
            "stream_no": reference.stream_no,
            "ward": reference.ward_name,
            "state": state,
            "verification": row.get("verification", "NONE"),
            "registered": reference.registered,
            "votes": {},
            "checks": {
                check["code"]: check["status"] for check in validation.get("checks", [])
            },
            "form_url": row.get("public_url"),
            "form_version": row.get("version"),
        }

    def _published_payload(
        self, reference, row: dict[str, Any], payload: dict[str, Any], turnout: float | None
    ) -> dict[str, Any]:
        validation = _load_json(row.get("validation_json")) or {}
        valid = sum(int(value) for value in payload.get("votes", {}).values())
        rejected = int(payload.get("rejected", 0))
        return {
            "stream_key": reference.stream_key,
            "station_name": reference.station_name,
            "stream_no": reference.stream_no,
            "ward": reference.ward_name,
            "state": row.get("state", TrustState.PUBLISHED.value),
            "verification": row.get("verification", "NONE"),
            "registered": reference.registered,
            "votes": payload.get("votes", {}),
            "rejected": rejected,
            "valid": valid,
            "cast": valid + rejected,
            "turnout": turnout,
            "checks": {
                check["code"]: check["status"] for check in validation.get("checks", [])
            },
            "form_url": row.get("public_url"),
            "source_url": row.get("source_url"),
            "form_version": row.get("version"),
            "published_at": row.get("discovered_at"),
        }

    def _append_outlier_anomalies(
        self, published: list[dict[str, Any]], current: dict[str, dict[str, Any]]
    ) -> None:
        by_ward: dict[str, list[tuple[str, dict[str, int]]]] = defaultdict(list)
        for row in published:
            by_ward[row["ward_name"]].append((row["stream_key"], row["votes"]))
        for ward, rows in by_ward.items():
            for candidate_id, stream_keys in vote_share_outliers(rows).items():
                for stream_key in stream_keys:
                    form = current.get(stream_key, {})
                    self.db.add_anomaly(
                        stream_key,
                        "V11",
                        "INFO",
                        f"Statistical curiosity: {candidate_id} share is >3σ from the {ward} mean. Human attention only; not a fraud conclusion.",
                        form.get("public_url"),
                    )

    def _election_status(self) -> str:
        override = self.db.get_metadata("election_status")
        if override:
            return override
        now = time.time()
        polls_open = 1784170800  # 2026-07-16 06:00 EAT
        polls_close = 1784210400  # 2026-07-16 17:00 EAT
        if now < polls_open:
            return "PRE_POLL"
        if now < polls_close:
            return "POLLING"
        return "COUNTING"
