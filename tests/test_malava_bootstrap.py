from __future__ import annotations

import json
from pathlib import Path

import pytest

from olkalou_engine.archive import (
    _bootstrap_streams_from_portal,
    build_archive_payload,
    load_historical_bundle,
)
from olkalou_engine.models import PortalForm


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_bootstrap_profile(root: Path, *, expected: int = 2) -> None:
    election_dir = root / "data" / "elections" / "malava-test"
    election_dir.mkdir(parents=True)
    profile = {
        "schema": "kenya.election.profile.v1",
        "id": "malava-test",
        "mode": "ARCHIVE",
        "election": {
            "title": "Malava OCR test",
            "constituency": "MALAVA",
            "code": "201",
            "county": "KAKAMEGA",
            "county_code": "037",
            "date": "2025-11-27",
            "position": "Member of the National Assembly",
        },
        "portal": {
            "index_url": "https://example.test/index",
            "constituency": "MALAVA",
            "expected_forms": expected,
            "bootstrap_streams_from_portal": True,
        },
        "register": {
            "total": 0,
            "streams_total": expected,
            "source": "pending",
            "source_url": None,
            "verified": False,
        },
        "candidate_reference": {
            "source": "test",
            "source_url": None,
            "ballot_order_verified": False,
        },
        "candidates": [
            {"id": "UDA", "ballot_no": None, "name": "David Ndakwa", "party": "UDA", "abbr": "UDA", "colour": "#000000", "bloc": "A"},
            {"id": "DAPK", "ballot_no": None, "name": "Seth Panyako", "party": "DAP-K", "abbr": "DAP-K", "colour": "#111111", "bloc": "B"},
        ],
        "official_declaration": {"candidate_totals": {}, "valid_votes": None},
        "blocs": {"A": ["UDA"], "B": ["DAPK"]},
        "methodology": {"note": "benchmark"},
        "ocr": {"candidate_list_complete": False, "benchmark_only": True},
    }
    streams = {
        "schema": "kenya.election.stream-register.v1",
        "election_id": "malava-test",
        "bootstrap_from_portal": True,
        "reference_verified": False,
        "streams": [],
        "ward_summary": [],
    }
    (election_dir / "election.json").write_text(json.dumps(profile), encoding="utf-8")
    (election_dir / "streams.json").write_text(json.dumps(streams), encoding="utf-8")


def _forms(count: int) -> list[PortalForm]:
    return [
        PortalForm(
            source_url=f"https://example.test/download/{index}",
            source_label=f"27/11/2025 - MNA TEST SCHOOL {index:02d} Reported",
            station_name="TEST SCHOOL",
            stream_no=index,
            form_type="35A",
        )
        for index in range(1, count + 1)
    ]


def test_repository_malava_profile_remains_review_only_before_or_after_bootstrap() -> None:
    bundle = load_historical_bundle(REPO_ROOT, "malava-2025")
    assert bundle.profile["portal"]["expected_forms"] == 198
    assert bundle.profile["ocr"]["benchmark_only"] is True
    # The repository may legitimately contain either the pre-sync empty roster
    # or the completed 198-row portal/form-header review roster. Neither state
    # is a certified register and neither may publish a constituency result.
    assert len(bundle.streams) in {0, 198}
    if bundle.streams:
        assert all(row.get("registered") is None for row in bundle.streams)
        assert all(
            row.get("reference_state") in {"PORTAL_BOOTSTRAP", "FORM_HEADER_OCR"}
            for row in bundle.streams
        )
    payload = build_archive_payload(bundle)
    assert payload["status"] == "OCR_BENCHMARK"
    assert payload["reference"]["complete"] is False
    assert payload["reference"]["candidate_list_complete"] is False
    assert payload["archive"]["stream_results_complete"] is False
    assert payload["archive"]["tally_source"] == "NO_VERIFIED_TALLY"
    assert payload["coverage"]["published"] == 0


def test_portal_bootstrap_requires_exact_complete_assignment_count(tmp_path: Path) -> None:
    _write_bootstrap_profile(tmp_path, expected=2)
    bundle = load_historical_bundle(tmp_path, "malava-test")

    with pytest.raises(RuntimeError, match="No partial stream roster was written"):
        _bootstrap_streams_from_portal(bundle, _forms(1), portal_reported=2)

    stored = json.loads((bundle.election_dir / "streams.json").read_text(encoding="utf-8"))
    assert stored["streams"] == []


def test_portal_bootstrap_writes_stable_review_only_rows(tmp_path: Path) -> None:
    _write_bootstrap_profile(tmp_path, expected=2)
    bundle = load_historical_bundle(tmp_path, "malava-test")

    assert _bootstrap_streams_from_portal(bundle, _forms(2), portal_reported=2) is True
    assert len(bundle.streams) == 2
    assert all(row["registered"] is None for row in bundle.streams)
    assert all(row["reference_state"] == "PORTAL_BOOTSTRAP" for row in bundle.streams)
    assert len({row["stream_key"] for row in bundle.streams}) == 2
    assert len({row["polling_station_code"] for row in bundle.streams}) == 2
    assert bundle.streams_doc["bootstrapped_at"]

    # Re-running never overwrites an existing roster.
    assert _bootstrap_streams_from_portal(bundle, _forms(2), portal_reported=2) is False


def test_portal_bootstrap_preserves_ward_and_polling_centre_hierarchy(tmp_path: Path) -> None:
    _write_bootstrap_profile(tmp_path, expected=2)
    bundle = load_historical_bundle(tmp_path, "malava-test")
    forms = [
        PortalForm(
            source_url=f"https://example.test/download/{index}",
            source_label=f"27/11/2025 - MNA MUTSUMA PRIMARY SCHOOL {index:02d} Reported",
            station_name="MUTSUMA PRIMARY SCHOOL",
            polling_centre_name="MUTSUMA PRIMARY SCHOOL",
            polling_centre_code="001",
            ward_name="WEST KABRAS",
            ward_code="1002",
            stream_no=index,
            form_type="35A",
            hierarchy_path=["KAKAMEGA", "MALAVA", "WEST KABRAS", "MUTSUMA PRIMARY SCHOOL"],
        )
        for index in (1, 2)
    ]
    assert _bootstrap_streams_from_portal(bundle, forms, portal_reported=2)
    assert {row["ward_name"] for row in bundle.streams} == {"WEST KABRAS"}
    assert {row["polling_centre_name"] for row in bundle.streams} == {"MUTSUMA PRIMARY SCHOOL"}
    assert bundle.streams_doc["ward_summary"][0]["streams"] == 2


def test_form_header_identity_builds_official_hierarchy_key() -> None:
    from olkalou_engine.historical_identity import parse_form35a_identity

    identity = parse_form35a_identity(
        "Name of Polling Station MUTSUMA PRIMARY SCHOOL POLLING STATION 1 of 2 "
        "Code 037201100200101 Ward WEST KABRAS Code 1002 Constituency MALAVA Code 201",
        county_code="037",
        constituency_code="201",
    )
    assert identity.polling_station_code == "037201100200101"
    assert identity.ward_code == "1002"
    assert identity.polling_centre_code == "001"
    assert identity.polling_centre_name == "MUTSUMA PRIMARY SCHOOL"
    assert identity.ward_name == "WEST KABRAS"
    assert identity.stream_key == "201-1002-001-01"
