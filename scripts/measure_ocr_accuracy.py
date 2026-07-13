#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean


def load_truth(path: Path) -> dict[str, dict[str, int]]:
    truth: dict[str, dict[str, int]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = row.pop("stream_key").strip()
            truth[key] = {field: int(value) for field, value in row.items() if value not in {"", None}}
    return truth


def flatten(payload: dict) -> dict[str, int | None]:
    output: dict[str, int | None] = {
        "registered": payload.get("registered_form"),
        "rejected": payload.get("rejected"),
        "total_valid": payload.get("po_total_valid"),
        "total_cast": payload.get("total_cast_form"),
    }
    output.update({f"candidate_{key}": value for key, value in payload.get("votes", {}).items()})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure OCR/pipeline field accuracy against reviewed truth")
    parser.add_argument("truth_csv", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/state/engine.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("accuracy_report.md"))
    args = parser.parse_args()

    truth = load_truth(args.truth_csv)
    with sqlite3.connect(args.db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT stream_key,payload_json FROM results").fetchall()
    predictions = {row["stream_key"]: flatten(json.loads(row["payload_json"])) for row in rows}

    stats = defaultdict(lambda: {"truth": 0, "predicted": 0, "exact": 0, "errors": []})
    candidate_truth_totals = defaultdict(int)
    candidate_pred_totals = defaultdict(int)
    compared_streams = 0
    for stream_key, fields in truth.items():
        predicted = predictions.get(stream_key, {})
        if predicted:
            compared_streams += 1
        for field, expected in fields.items():
            stat = stats[field]
            stat["truth"] += 1
            actual = predicted.get(field)
            if actual is not None:
                stat["predicted"] += 1
                stat["errors"].append(abs(int(actual) - expected))
                if int(actual) == expected:
                    stat["exact"] += 1
            if field.startswith("candidate_"):
                candidate_truth_totals[field] += expected
                if actual is not None:
                    candidate_pred_totals[field] += int(actual)

    lines = [
        "# OCR accuracy report",
        "",
        f"Truth streams: **{len(truth)}**  ",
        f"Streams with pipeline output: **{compared_streams}**",
        "",
        "| Field | Truth cells | Coverage | Precision (exact/predicted) | Recall (exact/truth) | MAE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    all_truth = all_predicted = all_exact = 0
    for field in sorted(stats):
        stat = stats[field]
        all_truth += stat["truth"]
        all_predicted += stat["predicted"]
        all_exact += stat["exact"]
        coverage = stat["predicted"] / stat["truth"] if stat["truth"] else 0
        precision = stat["exact"] / stat["predicted"] if stat["predicted"] else 0
        recall = stat["exact"] / stat["truth"] if stat["truth"] else 0
        mae = mean(stat["errors"]) if stat["errors"] else 0
        lines.append(
            f"| {field} | {stat['truth']} | {coverage:.2%} | {precision:.2%} | {recall:.2%} | {mae:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Coverage: **{all_predicted / all_truth if all_truth else 0:.2%}**",
            f"- Exact precision: **{all_exact / all_predicted if all_predicted else 0:.2%}**",
            f"- Exact recall: **{all_exact / all_truth if all_truth else 0:.2%}**",
            "",
            "## Candidate total reproduction",
            "",
            "| Candidate field | Truth total | Pipeline total | Delta |",
            "|---|---:|---:|---:|",
        ]
    )
    for field in sorted(candidate_truth_totals):
        expected = candidate_truth_totals[field]
        actual = candidate_pred_totals[field]
        lines.append(f"| {field} | {expected:,} | {actual:,} | {actual - expected:+,} |")
    lines.extend(
        [
            "",
            "**Publication posture:** OCR remains a pre-fill unless the documented threshold is met and all statutory checks pass. Human double-entry remains available regardless of this score.",
        ]
    )
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
