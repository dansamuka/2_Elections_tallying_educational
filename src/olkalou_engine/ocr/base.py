from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import ExtractionResult


class Extractor(ABC):
    @abstractmethod
    def extract(self, *, stream_key: str, version: int, file_path: Path) -> ExtractionResult:
        raise NotImplementedError


class NoOpExtractor(Extractor):
    """Safe default: archives the form and routes it to human review without guessing."""

    def extract(self, *, stream_key: str, version: int, file_path: Path) -> ExtractionResult:
        del file_path
        return ExtractionResult(
            stream_key=stream_key,
            form_version=version,
            fields={},
            mean_confidence=0.0,
            engines=[],
            route="QUARANTINE",
        )
