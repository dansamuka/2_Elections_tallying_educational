#!/usr/bin/env python3
"""Heuristic Gazette-to-CSV helper.

This never marks data verified. It produces a review file that must be checked line by line
against the PDF before import_streams_csv.py is allowed to create production reference data.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROW_RE = re.compile(
    r"018\s+Nyandarua\s+091\s+Ol\s+Kalou\s+(?P<ward>045[3-7])\s+"
    r"(?P<ward_name>Karau|Kanjuiri\s+(?:Range|Ridge)|Mirangine|Kaimbaga|Rurii)\s+"
    r"(?P<center>\d{1,3})\s+(?P<center_name>.*?)\s+"
    r"(?P<polling_code>\d{12,16})\s+(?P<station_name>.*?)\s+(?P<registered>\d{1,3}(?:,\d{3})?)$",
    re.I,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("gazette_streams_REVIEW.csv"))
    args = parser.parse_args()
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("Install PDF helper dependencies: pip install -e '.[pdf]'") from exc
    lines = []
    with pdfplumber.open(args.pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            lines.extend(line.strip() for line in text.splitlines())
    records = []
    for line in lines:
        match = ROW_RE.search(re.sub(r"\s+", " ", line))
        if not match:
            continue
        code = match.group("polling_code")
        stream_no = int(code[-2:])
        station_code = code[:-2]
        records.append(
            {
                "stream_key": f"091-{station_code}-{stream_no:02d}",
                "station_code": station_code,
                "station_name": match.group("station_name").strip(),
                "stream_no": stream_no,
                "ward_code": match.group("ward"),
                "ward_name": match.group("ward_name").replace("Ridge", "Range").upper(),
                "registered": match.group("registered").replace(",", ""),
                "review_status": "REVIEW_REQUIRED",
                "source_line": line,
            }
        )
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys() if records else ["review_status"])
        writer.writeheader()
        writer.writerows(records)
    print(f"Extracted {len(records)} candidate rows to {args.output}. Do not import until manually verified.")


if __name__ == "__main__":
    main()
