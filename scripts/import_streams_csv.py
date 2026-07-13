#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

EXPECTED_WARDS = {
    "0453": "KARAU",
    "0454": "KANJUIRI RANGE",
    "0455": "MIRANGINE",
    "0456": "KAIMBAGA",
    "0457": "RURII",
}
EXPECTED_WARD_COUNTS = {"0453": 27, "0454": 32, "0455": 25, "0456": 27, "0457": 33}
EXPECTED_WARD_TOTALS = {
    "0453": 13_795,
    "0454": 15_585,
    "0455": 14_671,
    "0456": 13_766,
    "0457": 15_663,
}


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).upper()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the certified 144-row stream register CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/reference/streams.json"))
    parser.add_argument("--source", required=True, help="Exact Gazette/certified register citation")
    parser.add_argument("--source-url", required=True)
    args = parser.parse_args()

    rows = []
    with args.csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            ward_code = raw["ward_code"].strip().zfill(4)
            ward_name = normalize(raw["ward_name"])
            station_name = normalize(raw["station_name"])
            stream_no = int(raw["stream_no"])
            station_code = raw["station_code"].strip()
            stream_key = raw.get("stream_key", "").strip() or f"091-{station_code}-{stream_no:02d}"
            rows.append(
                {
                    "stream_key": stream_key,
                    "station_code": station_code,
                    "station_name": station_name,
                    "stream_no": stream_no,
                    "ward_code": ward_code,
                    "ward_name": ward_name,
                    "registered": int(raw["registered"]),
                    "baseline_2022": None,
                    "reference_status": "VERIFIED",
                }
            )

    errors = []
    if len(rows) != 144:
        errors.append(f"expected 144 rows, got {len(rows)}")
    if len({row["stream_key"] for row in rows}) != len(rows):
        errors.append("stream_key values are not unique")
    total = sum(row["registered"] for row in rows)
    if total != 73480:
        errors.append(f"registered-voter sum is {total}, expected 73,480")
    unknown = sorted({row["ward_code"] for row in rows} - set(EXPECTED_WARDS))
    if unknown:
        errors.append(f"unexpected ward codes: {unknown}")
    for row in rows:
        expected = EXPECTED_WARDS.get(row["ward_code"])
        if expected and row["ward_name"] != expected:
            errors.append(
                f"ward name mismatch for {row['stream_key']}: {row['ward_name']} != {expected}"
            )
        if not row["station_code"] or "PENDING" in row["station_code"].upper():
            errors.append(f"unresolved station code for {row['stream_key']}")
        if row["stream_no"] < 1:
            errors.append(f"invalid stream number for {row['stream_key']}")
        if row["registered"] < 0:
            errors.append(f"negative registered voters for {row['stream_key']}")
    for code, name in EXPECTED_WARDS.items():
        ward_rows = [row for row in rows if row["ward_code"] == code]
        if len(ward_rows) != EXPECTED_WARD_COUNTS[code]:
            errors.append(
                f"{name} has {len(ward_rows)} rows; expected {EXPECTED_WARD_COUNTS[code]}"
            )
        ward_total = sum(row["registered"] for row in ward_rows)
        if ward_total != EXPECTED_WARD_TOTALS[code]:
            errors.append(
                f"{name} registered total is {ward_total}; expected {EXPECTED_WARD_TOTALS[code]}"
            )
    if errors:
        raise SystemExit("Import blocked:\n- " + "\n- ".join(errors))

    ward_summary = []
    for code, name in EXPECTED_WARDS.items():
        ward_rows = [row for row in rows if row["ward_code"] == code]
        ward_summary.append(
            {
                "code": code,
                "name": name,
                "streams_total": len(ward_rows),
                "registered": sum(row["registered"] for row in ward_rows),
                "ward_total_verified": True,
            }
        )
    payload = {
        "schema": "olkalou.streams.v2",
        "constituency": {"code": "091", "name": "OL KALOU", "county": "NYANDARUA"},
        "register_source": args.source,
        "register_source_url": args.source_url,
        "register_source_verified": True,
        "register_total": total,
        "ward_summary": ward_summary,
        "streams": sorted(rows, key=lambda row: (row["ward_code"], row["station_code"], row["stream_no"])),
        "notes": ["Imported from operator-reviewed official CSV. Production checks passed."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}: 144 streams, {total:,} registered voters")


if __name__ == "__main__":
    main()
