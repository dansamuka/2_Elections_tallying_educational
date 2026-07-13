from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Protocol

from ..config import Settings
from ..models import ExtractionField, ExtractionResult
from .base import Extractor
from .preprocess import prepare_rois
from .words import words_to_int


@dataclass(frozen=True)
class OCRValue:
    text: str
    confidence: float


class CellEngine(Protocol):
    name: str

    def read_cells(self, cells: dict[str, Path], *, full_page: Path, roi_map: dict) -> dict[str, OCRValue]: ...


def numeric_value(text: str) -> int | None:
    compact = re.sub(r"[^0-9]", "", text)
    return int(compact) if compact else None


class GoogleVisionEngine:
    name = "gcv"

    def __init__(self, credentials_json: Path | None = None):
        if credentials_json:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(credentials_json))
        try:
            from google.cloud import vision
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install OCR dependencies: pip install -e '.[ocr]'") from exc
        self.vision = vision
        self.client = vision.ImageAnnotatorClient()

    def read_cells(self, cells: dict[str, Path], *, full_page: Path, roi_map: dict) -> dict[str, OCRValue]:
        del full_page, roi_map
        output: dict[str, OCRValue] = {}
        for name, path in cells.items():
            response = self.client.document_text_detection(
                image=self.vision.Image(content=path.read_bytes())
            )
            if response.error.message:
                raise RuntimeError(f"Google Vision error for {name}: {response.error.message}")
            annotation = response.full_text_annotation
            confidences = []
            for page in annotation.pages:
                for block in page.blocks:
                    for paragraph in block.paragraphs:
                        for word in paragraph.words:
                            confidences.extend(
                                symbol.confidence for symbol in word.symbols if symbol.confidence
                            )
            output[name] = OCRValue(
                text=(annotation.text or "").strip(),
                confidence=mean(confidences) if confidences else 0.0,
            )
        return output


class TextractEngine:
    name = "textract"

    def __init__(self, region: str):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install OCR dependencies: pip install -e '.[ocr]'") from exc
        self.client = boto3.client("textract", region_name=region)

    def read_cells(self, cells: dict[str, Path], *, full_page: Path, roi_map: dict) -> dict[str, OCRValue]:
        queries = roi_map.get("textract_queries") or []
        if queries:
            response = self.client.analyze_document(
                Document={"Bytes": full_page.read_bytes()},
                FeatureTypes=["QUERIES"],
                QueriesConfig={"Queries": queries},
            )
            by_id = {block["Id"]: block for block in response.get("Blocks", [])}
            output: dict[str, OCRValue] = {}
            for block in response.get("Blocks", []):
                if block.get("BlockType") != "QUERY":
                    continue
                alias = block.get("Query", {}).get("Alias")
                for relation in block.get("Relationships", []):
                    if relation.get("Type") != "ANSWER":
                        continue
                    for answer_id in relation.get("Ids", []):
                        answer = by_id.get(answer_id, {})
                        if alias:
                            output[alias] = OCRValue(
                                text=answer.get("Text", ""),
                                confidence=float(answer.get("Confidence", 0.0)) / 100.0,
                            )
            # Queries may not cover words cells. Fill missing cells using per-cell handwriting OCR.
            missing = {name: path for name, path in cells.items() if name not in output}
            output.update(self._detect_cells(missing))
            return output
        return self._detect_cells(cells)

    def _detect_cells(self, cells: dict[str, Path]) -> dict[str, OCRValue]:
        output: dict[str, OCRValue] = {}
        for name, path in cells.items():
            response = self.client.detect_document_text(Document={"Bytes": path.read_bytes()})
            lines = [b for b in response.get("Blocks", []) if b.get("BlockType") == "LINE"]
            output[name] = OCRValue(
                text=" ".join(line.get("Text", "") for line in lines).strip(),
                confidence=mean(float(line.get("Confidence", 0.0)) / 100.0 for line in lines)
                if lines
                else 0.0,
            )
        return output


def merge_engine_outputs(
    outputs: dict[str, dict[str, OCRValue]], roi_map: dict
) -> dict[str, ExtractionField]:
    """Merge `<field>.numeral` and `<field>.words` cells into the extraction contract."""
    field_names = sorted({name.rsplit(".", 1)[0] for name in roi_map.get("fields", {})})
    merged: dict[str, ExtractionField] = {}
    for field in field_names:
        numeral_key = f"{field}.numeral"
        words_key = f"{field}.words"
        values: dict[str, int | None] = {}
        confidences: list[float] = []
        words_texts: list[OCRValue] = []
        for engine_name, engine_output in outputs.items():
            item = engine_output.get(numeral_key)
            if item:
                values[engine_name] = numeric_value(item.text)
                confidences.append(item.confidence)
            words_item = engine_output.get(words_key)
            if words_item:
                words_texts.append(words_item)
        non_null = [value for value in values.values() if value is not None]
        consensus = bool(non_null) and len(non_null) == len(outputs) and len(set(non_null)) == 1
        value = non_null[0] if consensus else (non_null[0] if len(non_null) == 1 else None)
        best_words = max(words_texts, key=lambda item: item.confidence) if words_texts else None
        words_value = words_to_int(best_words.text) if best_words else None
        merged[field] = ExtractionField(
            value=value,
            confidence=min(confidences) if confidences else 0.0,
            engine_values=values,
            words_value=words_value,
            words_raw=best_words.text if best_words else None,
            consensus=consensus and (words_value is None or words_value == value),
        )
    return merged


class DualCloudExtractor(Extractor):
    def __init__(self, settings: Settings, engines: list[CellEngine] | None = None):
        self.settings = settings
        self.engines = engines or [
            GoogleVisionEngine(settings.gcv_credentials_json),
            TextractEngine(settings.aws_region),
        ]

    def extract(self, *, stream_key: str, version: int, file_path: Path) -> ExtractionResult:
        with tempfile.TemporaryDirectory(prefix=f"olkalou-{stream_key}-") as directory:
            work_dir = Path(directory)
            rectified, cells, roi_map = prepare_rois(
                file_path, self.settings.path(self.settings.form_roi_map), work_dir
            )
            outputs = {
                engine.name: engine.read_cells(cells, full_page=rectified, roi_map=roi_map)
                for engine in self.engines
            }
            fields = merge_engine_outputs(outputs, roi_map)
            confidences = [field.confidence for field in fields.values()]
            all_consensus = bool(fields) and all(field.consensus for field in fields.values())
            return ExtractionResult(
                stream_key=stream_key,
                form_version=version,
                fields=fields,
                mean_confidence=mean(confidences) if confidences else 0.0,
                engines=[engine.name for engine in self.engines],
                route="AUTO_VERIFY" if all_consensus else "QUARANTINE",
            )
