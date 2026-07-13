from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from olkalou_engine.archive import (
    build_archive_payload,
    build_catalog,
    import_verified_results,
    load_historical_bundle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def copy_banissa(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = REPO_ROOT / "data" / "elections" / "banissa-2025"
    target = root / "data" / "elections" / "banissa-2025"
    target.parent.mkdir(parents=True)
    shutil.copytree(source, target)
    return root


def test_banissa_reference_frame_is_complete() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "banissa-2025")
    assert len(bundle.streams) == 81
    assert sum(int(row["registered"]) for row in bundle.streams) == 32_703
    assert [candidate["id"] for candidate in bundle.candidates] == ["UDA", "UPA"]


def test_archive_payload_withholds_stream_replay_until_forms_are_transcribed(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    payload = build_archive_payload(bundle)

    assert payload["schema"] == "kenya.election.archive.v1"
    assert payload["coverage"]["streams_total"] == 81
    assert payload["coverage"]["published"] == 0
    assert payload["archive"]["replay_available"] is False
    assert payload["archive"]["tally_source"] == "OFFICIAL_DECLARATION"
    assert payload["totals"]["valid_votes"] == 11_671


def test_imported_stream_must_pass_statutory_checks(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    reference = bundle.streams[0]
    csv_path = root / "one-stream.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "stream_key", "reported_at", "form_url", "verification",
                "registered_form", "UDA", "UPA", "rejected", "po_total_valid",
                "total_cast_form", "reviewer_a", "reviewer_b", "notes",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "stream_key": reference["stream_key"],
            "reported_at": "2025-11-27T19:00:00Z",
            "form_url": "https://example.test/form-35a.pdf",
            "verification": "HUMAN",
            "registered_form": reference["registered"],
            "UDA": 100,
            "UPA": 20,
            "rejected": 2,
            "po_total_valid": 120,
            "total_cast_form": 122,
            "reviewer_a": "A",
            "reviewer_b": "B",
            "notes": "fixture",
        })

    imported = import_verified_results(bundle, csv_path)
    assert len(imported["results"]) == 1
    assert set(imported["results"][0]["checks"].values()) == {"PASS"}

    payload = build_archive_payload(bundle)
    assert payload["coverage"]["published"] == 1
    assert payload["archive"]["replay_available"] is False
    assert payload["streams"][0]["state"] == "PUBLISHED"


def test_import_rejects_register_mismatch(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    reference = bundle.streams[0]
    csv_path = root / "bad.csv"
    csv_path.write_text(
        "stream_key,reported_at,form_url,verification,registered_form,UDA,UPA,rejected,po_total_valid,total_cast_form\n"
        f"{reference['stream_key']},2025-11-27T19:00:00Z,,HUMAN,1,1,0,0,1,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="V07"):
        import_verified_results(bundle, csv_path)


def test_catalog_points_to_generated_archive_payload(tmp_path: Path) -> None:
    root = copy_banissa(tmp_path)
    bundle = load_historical_bundle(root, "banissa-2025")
    build_archive_payload(bundle)
    catalog = build_catalog(root)
    assert catalog["default"] == "banissa-2025"
    assert catalog["elections"][0]["data_url"].endswith("banissa-2025.json")
    stored = json.loads((root / "data/public/elections/catalog.json").read_text(encoding="utf-8"))
    assert stored == catalog
