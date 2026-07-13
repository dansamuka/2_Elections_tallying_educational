from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install OCR dependencies: pip install -e '.[ocr]'") from exc
    return cv2


def render_input(source: Path, work_dir: Path) -> Path:
    """Render the first page of a PDF or copy an image into a deterministic work area."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() != ".pdf":
        return source
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("PDF OCR requires pypdfium2 from the ocr extra") from exc
    pdf = pdfium.PdfDocument(str(source))
    if len(pdf) < 1:
        raise ValueError(f"PDF has no pages: {source}")
    bitmap = pdf[0].render(scale=3.0)
    target = work_dir / "page-1.png"
    bitmap.to_pil().save(target)
    return target


def rectify_to_template(image_path: Path, roi_map: dict[str, Any], work_dir: Path) -> Path:
    """Rectify a form to the reference frame using ORB/homography, or strict resize fallback."""
    cv2 = _cv2()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Unable to read image: {image_path}")
    size = roi_map.get("reference_size")
    if not size or len(size) != 2:
        raise ValueError("ROI map requires reference_size [width, height]")
    width, height = [int(v) for v in size]
    reference_name = roi_map.get("reference_image")
    reference_path = None
    if reference_name:
        candidate = Path(reference_name)
        reference_path = candidate if candidate.is_absolute() else Path(roi_map["_map_dir"]) / candidate

    rectified = None
    if reference_path and reference_path.exists():
        reference = cv2.imread(str(reference_path))
        if reference is None:
            raise ValueError(f"Unable to read reference image: {reference_path}")
        gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=5000)
        key_ref, desc_ref = orb.detectAndCompute(gray_ref, None)
        key_img, desc_img = orb.detectAndCompute(gray_image, None)
        if desc_ref is not None and desc_img is not None:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            pairs = matcher.knnMatch(desc_img, desc_ref, k=2)
            good = [a for a, b in pairs if a.distance < 0.75 * b.distance]
            if len(good) >= 20:
                import numpy as np

                src = np.float32([key_img[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                dst = np.float32([key_ref[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
                if matrix is not None and mask is not None and int(mask.sum()) >= 12:
                    rectified = cv2.warpPerspective(image, matrix, (reference.shape[1], reference.shape[0]))
                    rectified = cv2.resize(rectified, (width, height))
    if rectified is None:
        if not roi_map.get("allow_resize_fallback", False):
            raise ValueError(
                "Template homography could not be established and resize fallback is disabled"
            )
        rectified = cv2.resize(image, (width, height))

    target = work_dir / "rectified.png"
    cv2.imwrite(str(target), rectified)
    return target


def enhanced_crop(image, coordinates: list[int]):
    cv2 = _cv2()
    x, y, w, h = [int(v) for v in coordinates]
    crop = image[y : y + h, x : x + w]
    if crop.size == 0:
        raise ValueError(f"Empty ROI crop: {coordinates}")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
    )


def prepare_rois(source: Path, roi_map_path: Path, work_dir: Path) -> tuple[Path, dict[str, Path], dict[str, Any]]:
    roi_map = json.loads(roi_map_path.read_text(encoding="utf-8"))
    if roi_map.get("status") != "VERIFIED":
        raise ValueError("ROI map is not VERIFIED")
    roi_map["_map_dir"] = str(roi_map_path.parent)
    rendered = render_input(source, work_dir)
    rectified = rectify_to_template(rendered, roi_map, work_dir)
    cv2 = _cv2()
    image = cv2.imread(str(rectified))
    fields = roi_map.get("fields", {})
    if not fields:
        raise ValueError("ROI map has no fields")
    crops: dict[str, Path] = {}
    crop_dir = work_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for name, coordinates in fields.items():
        crop = enhanced_crop(image, coordinates)
        target = crop_dir / f"{name.replace('.', '__')}.png"
        cv2.imwrite(str(target), crop)
        crops[name] = target
    return rectified, crops, roi_map
