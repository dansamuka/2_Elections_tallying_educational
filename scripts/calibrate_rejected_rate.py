#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        raise ValueError("No values")
    index = (len(values) - 1) * p
    low = int(index)
    high = min(low + 1, len(values) - 1)
    fraction = index - low
    return values[low] * (1 - fraction) + values[high] * fraction


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate V05 from reviewed comparable forms")
    parser.add_argument("--db", type=Path, default=Path("data/state/engine.sqlite3"))
    parser.add_argument("--lower", type=float, default=0.025)
    parser.add_argument("--upper", type=float, default=0.975)
    args = parser.parse_args()
    with sqlite3.connect(args.db) as conn:
        rows = conn.execute("SELECT payload_json FROM results").fetchall()
    rates = []
    for (raw,) in rows:
        payload = json.loads(raw)
        valid = sum(int(v) for v in payload.get("votes", {}).values())
        rejected = int(payload.get("rejected", 0))
        cast = valid + rejected
        if cast:
            rates.append(rejected / cast)
    if len(rates) < 30:
        raise SystemExit(f"Calibration blocked: at least 30 reviewed forms required, found {len(rates)}")
    low = max(0.0, percentile(rates, args.lower))
    high = min(1.0, percentile(rates, args.upper))
    print(f"forms={len(rates)}")
    print(f"REJECTED_RATE_LOW={low:.6f}")
    print(f"REJECTED_RATE_HIGH={high:.6f}")


if __name__ == "__main__":
    main()
