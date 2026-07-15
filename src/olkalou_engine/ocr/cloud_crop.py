from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from statistics import mean
from typing import Any


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text or "")


def _vision_client(credentials_json: Path | None = None):
    if credentials_json:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_json)
    try:
        from google.cloud import vision
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Google crop OCR requires google-cloud-vision; install the historical-ocr extra"
        ) from exc
    return vision, vision.ImageAnnotatorClient()


@dataclass
class GoogleCropOCR:
    """Reusable, request-bounded Google Vision reader for numeric field crops.

    A single client is reused for the whole OCR run. Request limits and retry
    bounds prevent a malformed form batch from creating unbounded cloud cost.
    Returned values remain OCR evidence only and never bypass human review.
    """

    credentials_json: Path
    max_requests: int = 250
    max_attempts: int = 3
    timeout_seconds: float = 20.0
    retry_delay_seconds: float = 1.0
    _vision: Any = dataclass_field(init=False, repr=False)
    _client: Any = dataclass_field(init=False, repr=False)
    _stats: dict[str, Any] = dataclass_field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_requests < 0:
            raise ValueError("max_requests must be non-negative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self._vision, self._client = _vision_client(self.credentials_json)
        self._stats = {
            "engine": "gcv-document-text-crop",
            "request_limit": self.max_requests,
            "requests": 0,
            "fields_considered": 0,
            "responses": 0,
            "usable_values": 0,
            "rejected_values": 0,
            "failures": 0,
            "retries": 0,
            "skipped_request_limit": 0,
        }

    @property
    def stats(self) -> dict[str, Any]:
        return dict(self._stats)

    def _call(self, image_bytes: bytes):
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if self._stats["requests"] >= self.max_requests:
                self._stats["skipped_request_limit"] += 1
                return None
            self._stats["requests"] += 1
            try:
                response = self._client.document_text_detection(
                    image=self._vision.Image(content=image_bytes),
                    image_context=self._vision.ImageContext(language_hints=["en"]),
                    timeout=self.timeout_seconds,
                )
                if response.error.message:
                    raise RuntimeError(response.error.message)
                return response
            except Exception as exc:  # transient API/network failures are retried
                last_error = exc
                if attempt < self.max_attempts:
                    self._stats["retries"] += 1
                    time.sleep(self.retry_delay_seconds * attempt)
        self._stats["failures"] += 1
        if last_error is not None:
            raise last_error
        raise RuntimeError("Google Vision crop OCR failed without an error message")

    def read_numeric_crop(self, image_bytes: bytes, *, maximum: int | None) -> dict[str, Any]:
        self._stats["fields_considered"] += 1
        response = self._call(image_bytes)
        if response is None:
            return {
                "value": None,
                "confidence": 0.0,
                "raw": "",
                "engine": "gcv-document-text-crop",
                "skipped": "REQUEST_LIMIT",
            }

        self._stats["responses"] += 1
        annotation = response.full_text_annotation
        raw_text = (annotation.text or "").strip()
        digits = _digits(raw_text)
        value = int(digits) if digits and len(digits) <= 5 else None
        rejected_reason = None
        if value is not None and maximum is not None and value > maximum:
            rejected_reason = "ABOVE_REGISTERED_MAXIMUM"
            value = None

        confidences: list[float] = []
        for page in annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        for symbol in word.symbols:
                            if symbol.confidence:
                                confidences.append(float(symbol.confidence))

        if value is None:
            self._stats["rejected_values"] += 1
        else:
            self._stats["usable_values"] += 1

        return {
            "value": value,
            "confidence": mean(confidences) if confidences else 0.0,
            "raw": raw_text,
            "engine": "gcv-document-text-crop",
            "rejected_reason": rejected_reason,
        }


# These three controls are the target/inputs of the exact-sum reconciler in
# ocr/handwriting.py (`_best_exact_candidate_sum` treats `total_valid` as the
# target every candidate value must add up to; `registered`/`rejected` feed
# the independent V02/V03/V07 arithmetic and reference cross-checks in
# historical_ocr.py). A misread here has outsized leverage on every candidate
# on the form, so these three always get a bounded Google Vision call
# regardless of local confidence -- unlike candidate cells, where a call is
# still only made when the local read is weak or ambiguous. Three fields per
# form is a small, predictable addition to the request budget (e.g. 3 x 144
# streams = 432 calls for Ol Kalou, well inside even the smallest non-trivial
# `cloud_request_limit` tier).
ALWAYS_VERIFY_FIELDS = frozenset({"registered", "rejected", "total_valid"})


def build_google_crop_reader(
    *,
    engine_mode: str,
    credentials_json: Path | None,
    max_requests: int,
    max_attempts: int = 3,
    timeout_seconds: float = 20.0,
) -> GoogleCropOCR | None:
    """Create a crop reader only for modes that deliberately allow cloud crops."""

    normalized = engine_mode.lower().strip()
    enabled_modes = {"auto", "gcv", "google", "dual", "dual-cloud", "gcv-textract", "tesseract-gcv-crop"}
    if normalized not in enabled_modes:
        return None
    if not credentials_json:
        if normalized == "tesseract-gcv-crop":
            raise RuntimeError(
                "tesseract-gcv-crop requires GCV_CREDENTIALS_JSON; no credentials file was configured"
            )
        return None
    return GoogleCropOCR(
        credentials_json=credentials_json,
        max_requests=max_requests,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )


def augment_cell_result_with_google(
    cell_result: dict[str, Any],
    *,
    reader: GoogleCropOCR | None,
    registered_maximum: int | None,
    minimum_local_confidence: float = 0.86,
    disagreement_trigger: bool = True,
    minimum_cloud_prefill_confidence: float = 0.65,
) -> dict[str, Any]:
    """Add bounded Google Vision alternatives using the exact deskewed crops.

    ``extract_form35a_numeric_cells`` can attach private ``_crop_png`` bytes to
    each field. Those bytes come from the same deskewed image used to calculate
    crop coordinates, avoiding the coordinate drift caused by re-cropping the
    original page. Private bytes are removed before returning.
    """

    fields = cell_result.setdefault("fields", {})
    attempted = 0
    succeeded = 0
    usable = 0
    skipped_limit = 0
    failures: list[dict[str, str]] = []

    for field_name, field in fields.items():
        crop_bytes = field.pop("_crop_png", None)
        if reader is None or not crop_bytes:
            continue

        local_value = field.get("value")
        local_conf = float(field.get("confidence", 0.0) or 0.0)
        candidates = list(field.get("candidates") or [])
        top_values = {
            int(item["value"])
            for item in candidates[:2]
            if item.get("value") is not None
        }
        local_disagreement = len(top_values) > 1
        should_call = (
            field_name in ALWAYS_VERIFY_FIELDS
            or local_value is None
            or local_conf < minimum_local_confidence
            or (disagreement_trigger and local_disagreement)
        )
        if not should_call:
            continue

        attempted += 1
        try:
            result = reader.read_numeric_crop(crop_bytes, maximum=registered_maximum)
            if result.get("skipped") == "REQUEST_LIMIT":
                skipped_limit += 1
                field.setdefault("cloud_evidence", []).append(result)
                continue
            succeeded += 1
            field.setdefault("cloud_evidence", []).append(result)
            if result["value"] is None:
                continue
            usable += 1
            candidate = {
                "value": int(result["value"]),
                "confidence": min(0.99, float(result["confidence"])),
                "observations": 1,
                "raw": [result["raw"]],
                "source": result["engine"],
            }
            replaced = False
            for index, existing in enumerate(candidates):
                if existing.get("value") == candidate["value"]:
                    if float(existing.get("confidence", 0.0)) < candidate["confidence"]:
                        candidates[index] = candidate
                    replaced = True
                    break
            if not replaced:
                candidates.append(candidate)
            candidates.sort(
                key=lambda item: (
                    float(item.get("confidence", 0.0)),
                    int(item.get("observations", 1)),
                ),
                reverse=True,
            )
            field["candidates"] = candidates[:6]

            cloud_conf = candidate["confidence"]
            should_surface = (
                local_value is None and cloud_conf >= minimum_cloud_prefill_confidence
            ) or (
                local_value is not None
                and local_conf < 0.45
                and cloud_conf >= max(minimum_cloud_prefill_confidence, local_conf + 0.15)
            )
            if should_surface:
                field["value"] = candidate["value"]
                field["confidence"] = cloud_conf
                field["source"] = candidate["source"]
        except Exception as exc:
            failures.append({"field": field_name, "message": str(exc)})

    cell_result["cloud_crop_ocr"] = {
        "engine": "gcv-document-text-crop",
        "attempted_fields": attempted,
        "successful_responses": succeeded,
        "usable_values": usable,
        "skipped_request_limit": skipped_limit,
        "failures": failures,
        "selective": True,
        "minimum_local_confidence": minimum_local_confidence,
        "minimum_cloud_prefill_confidence": minimum_cloud_prefill_confidence,
        "run_stats": reader.stats if reader is not None else None,
    }
    return cell_result
