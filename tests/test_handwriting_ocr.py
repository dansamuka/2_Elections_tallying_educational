from __future__ import annotations

from olkalou_engine.ocr.handwriting import numeric_value, reconcile_form35a_fields


def test_numeric_value_maps_common_handwriting_substitutions() -> None:
    assert numeric_value("O23") == 23
    assert numeric_value("I7S") == 175
    assert numeric_value("not a number") is None
    assert numeric_value("900", maximum=650) is None


def test_reconciliation_prefers_exact_candidate_arithmetic_over_row_numbers() -> None:
    parsed = {
        "fields": {
            "candidate_UDA": {"value": 1, "confidence": 0.78},
            "candidate_UPA": {"value": 2, "confidence": 0.78},
            "registered": {"value": 1, "confidence": 0.78},
            "rejected": {"value": 0, "confidence": 0.82},
            "total_valid": {"value": 216, "confidence": 0.82},
            "total_cast": {"value": 216, "confidence": 0.82},
        },
        "evidence": {},
    }
    cells = {
        "schema": "kenya.election.handwriting-cells.v1",
        "anchors_found": 5,
        "page_size": [4000, 5500],
        "fields": {
            "candidate_UDA": {
                "anchor": "HASSAN AHMED MAALIM",
                "candidates": [
                    {"value": 208, "confidence": 0.91, "observations": 5},
                    {"value": 1, "confidence": 0.72, "observations": 2},
                ],
            },
            "candidate_UPA": {
                "anchor": "MOHAMED NURDIN MAALIM",
                "candidates": [
                    {"value": 8, "confidence": 0.90, "observations": 5},
                    {"value": 2, "confidence": 0.71, "observations": 2},
                ],
            },
            "registered": {"anchor": "REGISTERED VOTERS", "candidates": [{"value": 1, "confidence": 0.45, "observations": 1}]},
            "rejected": {"anchor": "REJECTED BALLOT PAPERS", "candidates": [{"value": 0, "confidence": 0.90, "observations": 4}]},
            "total_valid": {"anchor": "TOTAL VALID VOTES CAST", "candidates": [{"value": 216, "confidence": 0.92, "observations": 5}]},
        },
    }

    result = reconcile_form35a_fields(
        parsed,
        cells,
        {"registered": 630},
        ["UDA", "UPA"],
    )
    fields = result["fields"]
    assert fields["candidate_UDA"]["value"] == 208
    assert fields["candidate_UPA"]["value"] == 8
    assert fields["total_valid"]["value"] == 216
    assert fields["registered"]["value"] == 630
    assert fields["total_cast"]["value"] == 216
    assert fields["registered"]["source"] == "certified-register-hint"
    assert result["handwriting"]["anchors_found"] == 5


def test_incomplete_candidate_roster_does_not_force_subtotal_to_total_valid() -> None:
    parsed = {
        "fields": {
            "candidate_UDA": {"value": 1, "confidence": 0.78},
            "candidate_DAPK": {"value": 2, "confidence": 0.78},
            "total_valid": {"value": 400, "confidence": 0.88},
            "rejected": {"value": 3, "confidence": 0.88},
        },
        "evidence": {},
    }
    cells = {
        "schema": "kenya.election.handwriting-cells.v1",
        "anchors_found": 4,
        "page_size": [4000, 5500],
        "fields": {
            "candidate_UDA": {
                "anchor": "DAVID ATHMAN NDAKWA",
                "candidates": [
                    {"value": 210, "confidence": 0.94, "observations": 5},
                    {"value": 398, "confidence": 0.30, "observations": 1},
                ],
            },
            "candidate_DAPK": {
                "anchor": "SETH PANYAKO",
                "candidates": [
                    {"value": 150, "confidence": 0.93, "observations": 5},
                    {"value": 2, "confidence": 0.40, "observations": 1},
                ],
            },
            "total_valid": {
                "anchor": "TOTAL VALID VOTES CAST",
                "candidates": [{"value": 400, "confidence": 0.95, "observations": 5}],
            },
            "rejected": {
                "anchor": "REJECTED BALLOT PAPERS",
                "candidates": [{"value": 3, "confidence": 0.94, "observations": 5}],
            },
        },
    }

    result = reconcile_form35a_fields(
        parsed,
        cells,
        None,
        ["UDA", "DAPK"],
        candidate_list_complete=False,
    )

    assert result["fields"]["candidate_UDA"]["value"] == 210
    assert result["fields"]["candidate_DAPK"]["value"] == 150
    assert result["fields"]["total_valid"]["value"] == 400
    assert result["fields"]["total_cast"]["value"] == 403
    assert result["handwriting"]["candidate_list_complete"] is False
