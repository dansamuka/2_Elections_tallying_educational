#!/usr/bin/env python3
"""Measure historical Form 35A OCR against human-confirmed review rows.

The script reads the immutable per-page extraction JSON produced by
``run_historical_ocr``. It never reads verified/public tally rows, so a benchmark
can be run while the atomic stream register or candidate roster is still
incomplete.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


CONTROL_COLUMNS = {
    "registered_form": "registered",
    "rejected": "rejected",
    "po_total_valid": "total_valid",
    "total_cast_form": "total_cast",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def load_candidate_ids(root: Path, election_id: str) -> list[str]:
    profile = read_json(root / "data" / "elections" / election_id / "election.json")
    return [str(candidate["id"]) for candidate in profile.get("candidates", [])]


def load_truth(path: Path, candidate_ids: list[str]) -> dict[str, dict[str, int]]:
    truth: dict[str, dict[str, int]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "stream_key" not in reader.fieldnames:
            raise ValueError("truth CSV must contain stream_key")
        for line_no, row in enumerate(reader, start=2):
            stream_key = str(row.get("stream_key") or "").strip()
            if not stream_key:
                continue
            fields: dict[str, int] = {}
            for candidate_id in candidate_ids:
                value = as_int(row.get(candidate_id))
                if value is not None:
                    fields[f"candidate_{candidate_id}"] = value
            for column, field in CONTROL_COLUMNS.items():
                value = as_int(row.get(column))
                if value is not None:
                    fields[field] = value
            if not fields:
                continue
            if stream_key in truth:
                raise ValueError(f"line {line_no}: duplicate stream_key {stream_key}")
            truth[stream_key] = fields
    return truth


def extraction_fields(extraction: dict[str, Any]) -> dict[str, int]:
    fields = (extraction.get("parsed") or {}).get("fields") or {}
    output: dict[str, int] = {}
    for name, item in fields.items():
        if not isinstance(item, dict):
            continue
        value = as_int(item.get("value"))
        if value is not None:
            output[str(name)] = value
    return output


def extraction_rank(extraction: dict[str, Any]) -> tuple[int, float, int]:
    route = str(extraction.get("route") or "")
    route_rank = {
        "READY_FOR_DOUBLE_REVIEW": 3,
        "OCR_BENCHMARK_REVIEW": 2,
        "QUARANTINE": 1,
    }.get(route, 0)
    return (
        route_rank,
        float(extraction.get("confidence") or 0.0),
        len(extraction_fields(extraction)),
    )


def load_predictions(root: Path, election_id: str) -> dict[str, dict[str, int]]:
    directory = root / "data" / "elections" / election_id / "ocr" / "extractions"
    best: dict[str, dict[str, Any]] = {}
    if not directory.exists():
        return {}
    for path in sorted(directory.glob("*.json")):
        try:
            extraction = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if extraction.get("form_type") != "35A":
            continue
        stream_key = str(extraction.get("stream_key") or "").strip()
        if not stream_key:
            continue
        current = best.get(stream_key)
        if current is None or extraction_rank(extraction) > extraction_rank(current):
            best[stream_key] = extraction
    return {stream_key: extraction_fields(extraction) for stream_key, extraction in best.items()}


def calculate_metrics(
    truth: dict[str, dict[str, int]],
    predictions: dict[str, dict[str, int]],
) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"truth": 0, "predicted": 0, "exact": 0, "absolute_errors": []}
    )
    candidate_truth_totals: dict[str, int] = defaultdict(int)
    candidate_predicted_totals: dict[str, int] = defaultdict(int)
    matched_streams = 0

    for stream_key, expected_fields in truth.items():
        predicted_fields = predictions.get(stream_key, {})
        if predicted_fields:
            matched_streams += 1
        for field, expected in expected_fields.items():
            stat = stats[field]
            stat["truth"] += 1
            actual = predicted_fields.get(field)
            if actual is not None:
                stat["predicted"] += 1
                error = abs(int(actual) - int(expected))
                stat["absolute_errors"].append(error)
                if error == 0:
                    stat["exact"] += 1
            if field.startswith("candidate_"):
                candidate_truth_totals[field] += int(expected)
                if actual is not None:
                    candidate_predicted_totals[field] += int(actual)

    all_truth = sum(int(row["truth"]) for row in stats.values())
    all_predicted = sum(int(row["predicted"]) for row in stats.values())
    all_exact = sum(int(row["exact"]) for row in stats.values())
    all_errors = [error for row in stats.values() for error in row["absolute_errors"]]

    field_metrics: dict[str, dict[str, Any]] = {}
    for field, stat in sorted(stats.items()):
        truth_cells = int(stat["truth"])
        predicted_cells = int(stat["predicted"])
        exact_cells = int(stat["exact"])
        errors = list(stat["absolute_errors"])
        field_metrics[field] = {
            "truth_cells": truth_cells,
            "predicted_cells": predicted_cells,
            "exact_cells": exact_cells,
            "coverage": predicted_cells / truth_cells if truth_cells else 0.0,
            "exact_precision": exact_cells / predicted_cells if predicted_cells else 0.0,
            "exact_recall": exact_cells / truth_cells if truth_cells else 0.0,
            "mae": mean(errors) if errors else None,
        }

    candidate_totals = {
        field: {
            "truth": candidate_truth_totals[field],
            "predicted": candidate_predicted_totals[field],
            "delta": candidate_predicted_totals[field] - candidate_truth_totals[field],
        }
        for field in sorted(candidate_truth_totals)
    }
    return {
        "truth_streams": len(truth),
        "prediction_streams": len(predictions),
        "matched_streams": matched_streams,
        "aggregate": {
            "truth_cells": all_truth,
            "predicted_cells": all_predicted,
            "exact_cells": all_exact,
            "coverage": all_predicted / all_truth if all_truth else 0.0,
            "exact_precision": all_exact / all_predicted if all_predicted else 0.0,
            "exact_recall": all_exact / all_truth if all_truth else 0.0,
            "mae": mean(all_errors) if all_errors else None,
        },
        "fields": field_metrics,
        "candidate_totals": candidate_totals,
    }


def fmt_percent(value: float) -> str:
    return f"{value:.2%}"


def fmt_mae(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def render_markdown(election_id: str, metrics: dict[str, Any]) -> str:
    aggregate = metrics["aggregate"]
    lines = [
        f"# Historical OCR accuracy report · {election_id}",
        "",
        f"Truth streams: **{metrics['truth_streams']}**  ",
        f"OCR streams available: **{metrics['prediction_streams']}**  ",
        f"Truth streams matched to OCR: **{metrics['matched_streams']}**",
        "",
        "| Field | Truth cells | Coverage | Exact precision | Exact recall | MAE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for field, stat in metrics["fields"].items():
        lines.append(
            f"| {field} | {stat['truth_cells']} | {fmt_percent(stat['coverage'])} | "
            f"{fmt_percent(stat['exact_precision'])} | {fmt_percent(stat['exact_recall'])} | "
            f"{fmt_mae(stat['mae'])} |"
        )
    lines.extend([
        "",
        "## Aggregate",
        "",
        f"- Coverage: **{fmt_percent(aggregate['coverage'])}**",
        f"- Exact precision: **{fmt_percent(aggregate['exact_precision'])}**",
        f"- Exact recall: **{fmt_percent(aggregate['exact_recall'])}**",
        f"- Mean absolute error: **{fmt_mae(aggregate['mae'])}**",
        "",
        "## Candidate total reproduction",
        "",
        "| Candidate field | Truth total | OCR total | Delta |",
        "|---|---:|---:|---:|",
    ])
    for field, totals in metrics["candidate_totals"].items():
        lines.append(
            f"| {field} | {totals['truth']:,} | {totals['predicted']:,} | {totals['delta']:+,} |"
        )
    if not metrics["candidate_totals"]:
        lines.append("| — | — | — | — |")
    lines.extend([
        "",
        "**Interpretation:** coverage measures whether OCR produced a value; exact precision measures how often produced values were exactly correct; exact recall penalises both missing and incorrect values. MAE shows the average absolute vote-count error where OCR produced a value.",
        "",
        "**Publication posture:** this report validates OCR only. Human-confirmed benchmark rows remain separate from verified election results, and no OCR value is published automatically.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure historical Form 35A extraction JSON against a human-confirmed truth CSV"
    )
    parser.add_argument("election_id")
    parser.add_argument("truth_csv", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    candidate_ids = load_candidate_ids(root, args.election_id)
    truth = load_truth(args.truth_csv, candidate_ids)
    predictions = load_predictions(root, args.election_id)
    metrics = calculate_metrics(truth, predictions)

    default_dir = root / "data" / "elections" / args.election_id / "ocr"
    output = args.output or default_dir / "accuracy_report.md"
    json_output = args.json_output or default_dir / "accuracy_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(args.election_id, metrics), encoding="utf-8")
    json_output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(json_output)


if __name__ == "__main__":
    main()
