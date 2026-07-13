from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = (len(values) - 1) * q
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - index) + values[hi] * (index - lo)


def hard_bounds(
    candidate_totals: dict[str, int], remaining_registered: int, observed_turnouts: list[float]
) -> dict[str, Any]:
    ranked = sorted(candidate_totals.items(), key=lambda item: (-item[1], item[0]))
    if not ranked:
        return {
            "leader": None,
            "margin": 0,
            "t1_hard_bound": {
                "remaining_registered": remaining_registered,
                "mathematically_decided": False,
            },
            "t2_capped_bound": {"max_remaining_votes": 0, "decided": False},
        }
    leader, leader_votes = ranked[0]
    runner_votes = ranked[1][1] if len(ranked) > 1 else 0
    margin = leader_votes - runner_votes
    turnout_cap = min(1.0, percentile(observed_turnouts, 0.95) if observed_turnouts else 0.70)
    max_remaining_votes = math.floor(remaining_registered * turnout_cap)
    return {
        "leader": leader,
        "margin": margin,
        "t1_hard_bound": {
            "remaining_registered": remaining_registered,
            "mathematically_decided": margin > remaining_registered,
        },
        "t2_capped_bound": {
            "turnout_cap": turnout_cap,
            "max_remaining_votes": max_remaining_votes,
            "decided": margin > max_remaining_votes,
        },
    }


def monte_carlo(
    *,
    published: list[dict[str, Any]],
    outstanding: list[dict[str, Any]],
    candidate_ids: list[str],
    simulations: int = 10_000,
    seed: int | None = None,
) -> dict[str, Any] | None:
    if not published or not outstanding or not candidate_ids or simulations <= 0:
        return None
    rng = random.Random(seed)
    constituency_totals = {candidate: 0 for candidate in candidate_ids}
    ward_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in published:
        for candidate in candidate_ids:
            constituency_totals[candidate] += int(row["votes"].get(candidate, 0))
        ward_rows[row["ward_name"]].append(row)

    overall_turnouts = [float(row["turnout"]) for row in published if row.get("turnout") is not None]
    overall_turnout = mean(overall_turnouts) if overall_turnouts else 0.60
    overall_votes = {
        candidate: sum(int(row["votes"].get(candidate, 0)) for row in published)
        for candidate in candidate_ids
    }
    overall_valid = sum(overall_votes.values()) or 1
    overall_shares = {candidate: overall_votes[candidate] / overall_valid for candidate in candidate_ids}

    final_margins: list[int] = []
    wins = {candidate: 0 for candidate in candidate_ids}
    for _ in range(simulations):
        totals = dict(constituency_totals)
        for stream in outstanding:
            ward = stream["ward_name"]
            rows = ward_rows.get(ward, [])
            turnout_values = [float(row["turnout"]) for row in rows if row.get("turnout") is not None]
            turnout_mu = mean(turnout_values) if turnout_values else overall_turnout
            turnout_sd = max(0.025, (max(turnout_values) - min(turnout_values)) / 4) if len(turnout_values) > 1 else 0.07
            sampled_turnout = min(0.95, max(0.20, rng.gauss(turnout_mu, turnout_sd)))
            cast = round(int(stream.get("registered") or 0) * sampled_turnout)

            ward_votes = {
                candidate: sum(int(row["votes"].get(candidate, 0)) for row in rows)
                for candidate in candidate_ids
            }
            ward_valid = sum(ward_votes.values())
            base_shares = (
                {candidate: ward_votes[candidate] / ward_valid for candidate in candidate_ids}
                if ward_valid > 0
                else overall_shares
            )
            concentration = max(8.0, min(80.0, len(rows) * 5.0))
            gammas = {
                candidate: rng.gammavariate(max(0.25, base_shares[candidate] * concentration), 1.0)
                for candidate in candidate_ids
            }
            gamma_sum = sum(gammas.values()) or 1.0
            allocated = 0
            for candidate in candidate_ids[:-1]:
                votes = round(cast * gammas[candidate] / gamma_sum)
                totals[candidate] += votes
                allocated += votes
            totals[candidate_ids[-1]] += max(0, cast - allocated)

        ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        wins[ranked[0][0]] += 1
        margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1]
        final_margins.append(margin)

    final_margins.sort()
    lo = final_margins[max(0, int(simulations * 0.05) - 1)]
    hi = final_margins[min(simulations - 1, int(simulations * 0.95))]
    return {
        "win_probability": {candidate: wins[candidate] / simulations for candidate in candidate_ids},
        "margin_ci90": [lo, hi],
        "method": f"ward-stratified Monte Carlo, n={simulations}",
        "assumptions_url": "/methodology.html#projection",
    }
