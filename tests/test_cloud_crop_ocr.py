from pathlib import Path
from types import SimpleNamespace

import pytest

from olkalou_engine.ocr import cloud_crop
from olkalou_engine.ocr.handwriting import reconcile_form35a_fields


class _Symbol:
    def __init__(self, confidence):
        self.confidence = confidence


def _response(text="184", confidence=0.98, error=""):
    word = SimpleNamespace(symbols=[_Symbol(confidence)])
    paragraph = SimpleNamespace(words=[word])
    block = SimpleNamespace(paragraphs=[paragraph])
    page = SimpleNamespace(blocks=[block])
    return SimpleNamespace(
        error=SimpleNamespace(message=error),
        full_text_annotation=SimpleNamespace(text=text, pages=[page]),
    )


def _reader(monkeypatch, responses, *, max_requests=10, max_attempts=3):
    calls = []

    class Client:
        def document_text_detection(self, **kwargs):
            calls.append(kwargs)
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

    fake_vision = SimpleNamespace(
        Image=lambda content: content,
        ImageContext=lambda language_hints: language_hints,
    )
    monkeypatch.setattr(cloud_crop, "_vision_client", lambda credentials_json=None: (fake_vision, Client()))
    monkeypatch.setattr(cloud_crop.time, "sleep", lambda seconds: None)
    return (
        cloud_crop.GoogleCropOCR(
            credentials_json=Path("credentials.json"),
            max_requests=max_requests,
            max_attempts=max_attempts,
        ),
        calls,
    )


def test_google_numeric_crop_parses_and_bounds(monkeypatch):
    reader, calls = _reader(monkeypatch, [_response("184")])
    result = reader.read_numeric_crop(b"x", maximum=500)
    assert result["value"] == 184
    assert result["confidence"] == pytest.approx(0.98)
    assert len(calls) == 1
    assert reader.stats["usable_values"] == 1


def test_google_numeric_crop_rejects_impossible_value(monkeypatch):
    reader, _ = _reader(monkeypatch, [_response("29060")])
    result = reader.read_numeric_crop(b"x", maximum=658)
    assert result["value"] is None
    assert result["rejected_reason"] == "ABOVE_REGISTERED_MAXIMUM"
    assert reader.stats["rejected_values"] == 1


def test_reader_reuses_client_and_obeys_request_limit(monkeypatch):
    reader, calls = _reader(
        monkeypatch,
        [_response("10"), _response("11")],
        max_requests=1,
        max_attempts=1,
    )
    first = reader.read_numeric_crop(b"a", maximum=100)
    second = reader.read_numeric_crop(b"b", maximum=100)
    assert first["value"] == 10
    assert second["skipped"] == "REQUEST_LIMIT"
    assert len(calls) == 1
    assert reader.stats["skipped_request_limit"] == 1


def test_transient_failure_retries_without_new_client(monkeypatch):
    reader, calls = _reader(
        monkeypatch,
        [RuntimeError("temporary"), _response("73")],
        max_requests=3,
        max_attempts=2,
    )
    result = reader.read_numeric_crop(b"a", maximum=100)
    assert result["value"] == 73
    assert len(calls) == 2
    assert reader.stats["retries"] == 1


def test_augment_uses_exact_private_crop_and_removes_it(monkeypatch):
    reader, calls = _reader(monkeypatch, [_response("184", confidence=0.96)])
    original = {
        "fields": {
            "candidate_A": {
                "value": 1,
                "confidence": 0.2,
                "candidates": [{"value": 1, "confidence": 0.2, "observations": 1}],
                "_crop_png": b"deskewed-crop",
            }
        }
    }
    result = cloud_crop.augment_cell_result_with_google(
        original,
        reader=reader,
        registered_maximum=500,
    )
    field = result["fields"]["candidate_A"]
    assert "_crop_png" not in field
    assert calls[0]["image"] == b"deskewed-crop"
    assert field["value"] == 184
    assert field["source"] == "gcv-document-text-crop"
    assert result["cloud_crop_ocr"]["usable_values"] == 1


def test_control_fields_are_always_verified_even_at_high_local_confidence(monkeypatch):
    # A misread `total_valid` (the exact-sum reconciler's target) or
    # `registered`/`rejected` (the V02/V03/V07 reference cross-checks) has
    # outsized leverage on every candidate on the form, so these three are
    # deliberately verified regardless of how confident the local read was --
    # unlike an ordinary candidate cell, which only gets a cloud call when
    # the local read is weak or the top two alternatives disagree.
    reader, calls = _reader(
        monkeypatch,
        [_response("184", confidence=0.9), _response("50", confidence=0.9)],
    )
    original = {
        "fields": {
            "total_valid": {
                "value": 184,
                "confidence": 0.97,
                "candidates": [{"value": 184, "confidence": 0.97, "observations": 3}],
                "_crop_png": b"deskewed-crop",
            },
            "candidate_A": {
                "value": 50,
                "confidence": 0.97,
                "candidates": [{"value": 50, "confidence": 0.97, "observations": 3}],
                "_crop_png": b"deskewed-crop",
            },
        }
    }
    result = cloud_crop.augment_cell_result_with_google(
        original,
        reader=reader,
        registered_maximum=500,
    )
    assert len(calls) == 1
    assert result["fields"]["total_valid"]["cloud_evidence"][0]["value"] == 184
    assert "cloud_evidence" not in result["fields"]["candidate_A"]
    assert result["cloud_crop_ocr"]["attempted_fields"] == 1


def test_no_reader_is_noop_but_private_bytes_are_removed():
    original = {
        "fields": {
            "candidate_A": {
                "value": 10,
                "confidence": 0.2,
                "_crop_png": b"private",
            }
        }
    }
    result = cloud_crop.augment_cell_result_with_google(
        original,
        reader=None,
        registered_maximum=100,
    )
    assert result is original
    assert "_crop_png" not in result["fields"]["candidate_A"]
    assert result["cloud_crop_ocr"]["attempted_fields"] == 0


def test_cloud_candidate_source_survives_arithmetic_reconciliation():
    parsed = {
        "fields": {
            "candidate_A": {"value": 1, "confidence": 0.1},
            "registered": {"value": 100, "confidence": 0.8},
            "rejected": {"value": 0, "confidence": 0.8},
            "total_valid": {"value": 84, "confidence": 0.8},
            "total_cast": {"value": 84, "confidence": 0.8},
        },
        "evidence": {},
    }
    cells = {
        "schema": "kenya.election.handwriting-cells.v1",
        "fields": {
            "candidate_A": {
                "candidates": [
                    {
                        "value": 84,
                        "confidence": 0.96,
                        "observations": 1,
                        "source": "gcv-document-text-crop",
                    }
                ]
            },
            "registered": {"candidates": [{"value": 100, "confidence": 0.9}]},
            "rejected": {"candidates": [{"value": 0, "confidence": 0.9}]},
            "total_valid": {"candidates": [{"value": 84, "confidence": 0.9}]},
        },
        "cloud_crop_ocr": {"attempted_fields": 1},
    }
    reconciled = reconcile_form35a_fields(
        parsed,
        cells,
        {"registered": 100},
        ["A"],
    )
    assert reconciled["fields"]["candidate_A"]["value"] == 84
    assert reconciled["fields"]["candidate_A"]["source"] == "gcv-document-text-crop"
    assert reconciled["handwriting"]["cloud_crop_ocr"]["attempted_fields"] == 1


def test_explicit_crop_mode_requires_credentials():
    with pytest.raises(RuntimeError, match="requires GCV_CREDENTIALS_JSON"):
        cloud_crop.build_google_crop_reader(
            engine_mode="tesseract-gcv-crop",
            credentials_json=None,
            max_requests=10,
        )
