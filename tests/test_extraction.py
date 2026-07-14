"""Tests for build_extractor()'s fail-safe behaviour (13/14 Jul 2026
dashboard review). Worker.__init__ calls this ONCE at startup -- before this
fix, any failure constructing DualCloudExtractor (missing google-cloud-vision
/boto3, a missing or invalid GCV_CREDENTIALS_JSON, an unreachable API)
propagated straight out and prevented the live worker from starting at all.
That is the one process this whole project cannot afford to crash on
election night. See extraction.py and Dockerfile for the paired fixes
(Dockerfile previously only installed `[s3]`, never `[ocr]`, so this exact
failure was live and waiting -- fixed there too).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from olkalou_engine.config import Settings
from olkalou_engine.extraction import build_extractor
from olkalou_engine.ocr.base import NoOpExtractor


def test_none_mode_returns_noop() -> None:
    settings = Settings(ENGINE_ROOT=Path("."), OCR_MODE="none")
    assert isinstance(build_extractor(settings), NoOpExtractor)


def test_unknown_mode_still_raises_clearly() -> None:
    settings = Settings(ENGINE_ROOT=Path("."), OCR_MODE="not-a-real-mode")
    with pytest.raises(ValueError, match="unknown"):
        build_extractor(settings)


def test_dual_cloud_falls_back_to_noop_when_construction_fails(caplog) -> None:
    """Exercised for real, not mocked: google-cloud-vision is not installed
    in this environment (matching exactly what the Dockerfile bug meant for
    production before it was fixed), so DualCloudExtractor's own constructor
    raises RuntimeError. build_extractor() must not propagate that -- the
    worker has to be able to start regardless.
    """
    settings = Settings(ENGINE_ROOT=Path("."), OCR_MODE="dual-cloud")
    extractor = build_extractor(settings)  # must not raise
    assert isinstance(extractor, NoOpExtractor)
    assert any("falling back to NoOpExtractor" in record.message for record in caplog.records)


def test_dual_cloud_succeeds_when_construction_works(monkeypatch) -> None:
    """The inverse case, with a fake engine so it's verified regardless of
    whether the real cloud SDKs happen to be installed: when construction
    genuinely succeeds, build_extractor must return the real extractor, not
    silently substitute NoOpExtractor even though nothing failed."""
    import olkalou_engine.extraction as extraction_module

    class FakeDualCloudExtractor:
        def __init__(self, settings):
            self.settings = settings

    fake_cloud_module = type("FakeCloudModule", (), {"DualCloudExtractor": FakeDualCloudExtractor})
    monkeypatch.setitem(__import__("sys").modules, "olkalou_engine.ocr.cloud", fake_cloud_module)

    settings = Settings(ENGINE_ROOT=Path("."), OCR_MODE="dual-cloud")
    extractor = extraction_module.build_extractor(settings)
    assert isinstance(extractor, FakeDualCloudExtractor)
