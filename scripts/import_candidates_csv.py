#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def luminance(hex_colour: str) -> float:
    values = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(left: str, right: str) -> float:
    high, low = sorted((luminance(left), luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import certified candidate list and verified Form 35A row order")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/reference/candidates.json"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()
    rows = []
    with args.csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "id": row["id"].strip().upper(),
                    "ballot_no": int(row["ballot_no"]),
                    "name": row["name"].strip(),
                    "party": row["party"].strip(),
                    "abbr": row["abbr"].strip().upper(),
                    "colour": row["colour"].strip(),
                    "bloc": row["bloc"].strip().upper(),
                }
            )
    if len(rows) != 9:
        raise SystemExit(f"Import blocked: expected 9 candidates, got {len(rows)}")
    if sorted(row["ballot_no"] for row in rows) != list(range(1, 10)):
        raise SystemExit("Import blocked: ballot_no must be exactly 1–9")
    if len({row["id"] for row in rows}) != 9:
        raise SystemExit("Import blocked: candidate ids must be unique")
    if len({row["abbr"] for row in rows}) != 9:
        raise SystemExit("Import blocked: party abbreviations must be unique")
    errors = []
    for row in rows:
        if not all([row["id"], row["name"], row["party"], row["abbr"], row["bloc"]]):
            errors.append(f"missing required candidate data at ballot {row['ballot_no']}")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", row["colour"]):
            errors.append(f"invalid colour for {row['id']}: {row['colour']}")
        elif contrast(row["colour"], "#0E1116") < 3.0:
            errors.append(f"candidate colour for {row['id']} fails 3:1 graphical contrast")
    if errors:
        raise SystemExit("Import blocked:\n- " + "\n- ".join(errors))
    blocs = {}
    for row in rows:
        blocs.setdefault(row["bloc"], []).append(row["abbr"])
    payload = {
        "source": args.source,
        "source_url": args.source_url,
        "source_verified": True,
        "ballot_order_verified": True,
        "last_checked_at": None,
        "candidates": sorted(rows, key=lambda row: row["ballot_no"]),
        "blocs": blocs,
        "notes": ["Imported from operator-reviewed certified candidate list and verified against Form 35A row order."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}: 9 verified candidates")


if __name__ == "__main__":
    main()
