from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_roi_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": "olkalou.form35a.roi.v1", "reference_size": None, "fields": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def crop_rois(image_path: Path, roi_map: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install OCR dependencies: pip install -e '.[ocr]'") from exc
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Unable to read image: {image_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    crops: dict[str, Path] = {}
    for field, coordinates in roi_map.get("fields", {}).items():
        x, y, w, h = [int(value) for value in coordinates]
        crop = image[y : y + h, x : x + w]
        target = output_dir / f"{field}.png"
        cv2.imwrite(str(target), crop)
        crops[field] = target
    return crops
