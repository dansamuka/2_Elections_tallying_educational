from __future__ import annotations

import logging

from .config import Settings
from .models import ExtractionResult, StreamResult
from .ocr.base import Extractor, NoOpExtractor

LOGGER = logging.getLogger(__name__)


def build_extractor(settings: Settings) -> Extractor:
    mode = settings.ocr_mode.lower()
    if mode in {"none", "manual", "noop"}:
        return NoOpExtractor()
    if mode in {"dual", "dual-cloud", "gcv-textract"}:
        # FIX (13/14 Jul 2026 dashboard review, matching the same gap found
        # in the historical pipeline's "auto" mode): this used to construct
        # DualCloudExtractor directly, and build_extractor() is called once
        # in Worker.__init__ -- ANY failure here (google-cloud-vision/boto3
        # not installed, a missing or expired GCV_CREDENTIALS_JSON, an
        # unreachable API) meant the live worker failed to even start.
        # That's the one process this whole project cannot afford to have
        # crash on election night. Fail open to NoOpExtractor instead: OCR
        # pre-fill is an optimisation (spec's own words) -- losing it means
        # every form goes to human double-entry review, slower but the
        # system keeps running. Fail loud in the log either way, so a
        # silently-disabled OCR pipeline doesn't go unnoticed for hours.
        try:
            from .ocr.cloud import DualCloudExtractor

            return DualCloudExtractor(settings)
        except Exception:
            LOGGER.exception(
                "OCR_MODE=dual-cloud requested but the extractor could not be "
                "constructed (missing package, bad/expired credentials, or "
                "unreachable API) -- falling back to NoOpExtractor. Every form "
                "will need manual double-entry review until this is fixed. "
                "Check google-cloud-vision/boto3 are installed and "
                "GCV_CREDENTIALS_JSON / AWS credentials are valid."
            )
            return NoOpExtractor()
    raise ValueError(
        f"OCR_MODE={settings.ocr_mode!r} is unknown. Use none or dual-cloud after certifying the ROI map."
    )


def extraction_to_stream_result(
    extraction: ExtractionResult,
    *,
    form_url: str,
    source_url: str,
    sha256: str,
) -> StreamResult | None:
    if not extraction.fields:
        return None
    vote_fields = {
        key.removeprefix("candidate_"): int(field.value)
        for key, field in extraction.fields.items()
        if key.startswith("candidate_") and field.value is not None
    }
    if not vote_fields:
        return None
    confidences = {key: field.confidence for key, field in extraction.fields.items()}
    required_fields = [field for key, field in extraction.fields.items() if not key.endswith("_optional")]
    words_fields = [field for field in required_fields if field.words_raw is not None]
    return StreamResult(
        stream_key=extraction.stream_key,
        form_version=extraction.form_version,
        registered_form=_value(extraction, "registered"),
        votes=vote_fields,
        rejected=_value(extraction, "rejected") or 0,
        po_total_valid=_value(extraction, "total_valid"),
        total_cast_form=_value(extraction, "total_cast"),
        field_confidence=confidences,
        engine_agreement=all(field.consensus for field in required_fields),
        words_agreement=bool(words_fields)
        and all(field.words_value == field.value for field in words_fields),
        form_url=form_url,
        source_url=source_url,
        sha256=sha256,
    )


def _value(extraction: ExtractionResult, key: str) -> int | None:
    field = extraction.fields.get(key)
    return field.value if field else None
