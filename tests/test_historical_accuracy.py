from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "measure_historical_ocr_accuracy.py"
SPEC = importlib.util.spec_from_file_location("measure_historical_ocr_accuracy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_historical_accuracy_reads_extractions_not_verified_tally(tmp_path: Path) -> None:
    election_id = "benchmark"
    election_dir = tmp_path / "data" / "elections" / election_id
    extraction_dir = election_dir / "ocr" / "extractions"
    extraction_dir.mkdir(parents=True)
    (election_dir / "election.json").write_text(
        json.dumps({"candidates": [{"id": "A"}, {"id": "B"}]}), encoding="utf-8"
    )
    extraction = {
        "form_type": "35A",
        "stream_key": "S1",
        "route": "OCR_BENCHMARK_REVIEW",
        "confidence": 0.8,
        "parsed": {
            "fields": {
                "candidate_A": {"value": 100},
                "candidate_B": {"value": 20},
                "registered": {"value": 500},
                "rejected": {"value": 2},
                "total_valid": {"value": 120},
                "total_cast": {"value": 122},
            }
        },
    }
    (extraction_dir / "s1.json").write_text(json.dumps(extraction), encoding="utf-8")

    truth_csv = tmp_path / "truth.csv"
    with truth_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "stream_key", "registered_form", "A", "B", "rejected",
                "po_total_valid", "total_cast_form",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "stream_key": "S1", "registered_form": 500, "A": 101, "B": 20,
            "rejected": 2, "po_total_valid": 121, "total_cast_form": 123,
        })

    candidates = MODULE.load_candidate_ids(tmp_path, election_id)
    truth = MODULE.load_truth(truth_csv, candidates)
    predictions = MODULE.load_predictions(tmp_path, election_id)
    metrics = MODULE.calculate_metrics(truth, predictions)

    assert metrics["matched_streams"] == 1
    assert metrics["aggregate"]["coverage"] == 1.0
    assert metrics["fields"]["candidate_B"]["exact_recall"] == 1.0
    assert metrics["fields"]["candidate_A"]["mae"] == 1
    assert metrics["candidate_totals"]["candidate_A"]["delta"] == -1
