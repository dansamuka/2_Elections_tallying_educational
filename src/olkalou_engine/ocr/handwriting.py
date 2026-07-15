from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class OCRCandidate:
    value: int
    confidence: float
    observations: int
    raw: tuple[str, ...] = ()
    source: str = "cell-ocr"


@dataclass(frozen=True)
class OCRLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _mapped_digits(text: str) -> str:
    # A second, non-whitelisted Tesseract pass can return letter-shaped
    # interpretations of handwriting. These substitutions are deliberately
    # conservative and only applied after every other character is discarded.
    table = str.maketrans({
        "O": "0", "Q": "0", "D": "0",
        "I": "1", "L": "1", "|": "1",
        "Z": "2", "S": "5", "B": "8", "G": "6",
    })
    return re.sub(r"[^0-9]", "", (text or "").upper().translate(table))


def numeric_value(text: str, *, maximum: int | None = None) -> int | None:
    raw = (text or "").upper()
    # Only apply letter-to-digit substitutions when every alphabetic glyph is
    # itself a common digit confusion. This prevents ordinary words such as
    # "BALLOT" from becoming a spurious 8 or 1.
    letters = set(re.findall(r"[A-Z]", raw))
    if letters - set("OQDILZSGB"):
        return None
    digits = _mapped_digits(raw)
    if not digits or len(digits) > 5:
        return None
    value = int(digits)
    if maximum is not None and value > maximum:
        return None
    return value


def _aggregate_candidates(
    observations: Iterable[tuple[int | None, float, str]],
    *,
    source: str = "cell-ocr",
) -> list[OCRCandidate]:
    grouped: dict[int, list[tuple[float, str]]] = {}
    for value, confidence, raw in observations:
        if value is None:
            continue
        grouped.setdefault(int(value), []).append((max(0.0, min(1.0, confidence)), raw))
    output: list[OCRCandidate] = []
    for value, rows in grouped.items():
        confs = [row[0] for row in rows]
        # Repetition across independent preprocessing/PSM passes is useful
        # evidence. The bonus is capped so weak repeated guesses do not become
        # "high confidence" merely by being repeated many times.
        repeat_bonus = min(0.18, 0.06 * max(0, len(rows) - 1))
        output.append(
            OCRCandidate(
                value=value,
                confidence=min(0.99, max(confs) * 0.7 + mean(confs) * 0.3 + repeat_bonus),
                observations=len(rows),
                raw=tuple(row[1] for row in rows if row[1]),
                source=source,
            )
        )
    output.sort(key=lambda item: (item.confidence, item.observations, -item.value), reverse=True)
    return output


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Layout-aware handwriting OCR requires opencv-python-headless") from exc
    return cv2


def _tesseract():
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Layout-aware handwriting OCR requires pytesseract") from exc
    return pytesseract


def _deskew_and_normalize(image):
    cv2 = _cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
    # Estimate the dominant form rotation from long horizontal rules. This is
    # intentionally bounded: scans can be slightly skewed, but a large inferred
    # angle usually means the line detector locked onto handwriting/noise.
    edges = cv2.Canny(gray, 70, 180)
    lines = cv2.HoughLinesP(
        edges,
        1,
        3.141592653589793 / 180,
        threshold=max(80, image.shape[1] // 10),
        minLineLength=max(120, image.shape[1] // 4),
        maxLineGap=30,
    )
    angles: list[float] = []
    if lines is not None:
        import math

        for raw in lines[:300]:
            x1, y1, x2, y2 = [int(v) for v in raw[0]]
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if -8.0 <= angle <= 8.0:
                angles.append(angle)
    angle = mean(angles) if angles else 0.0
    if abs(angle) >= 0.15:
        height, width = gray.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        image = cv2.warpAffine(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
    return image


def _page_lines(image) -> list[OCRLine]:
    pytesseract = _tesseract()
    from pytesseract import Output

    data = pytesseract.image_to_data(
        image,
        output_type=Output.DICT,
        config="--oem 1 --psm 11 -l eng",
    )
    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    count = len(data.get("text", []))
    for index in range(count):
        text = str(data["text"][index] or "").strip()
        if not text:
            continue
        try:
            conf = float(data.get("conf", ["-1"] * count)[index])
        except (TypeError, ValueError):
            conf = -1.0
        key = (
            int(data.get("block_num", [0] * count)[index]),
            int(data.get("par_num", [0] * count)[index]),
            int(data.get("line_num", [0] * count)[index]),
        )
        left = int(data.get("left", [0] * count)[index])
        top = int(data.get("top", [0] * count)[index])
        width = int(data.get("width", [0] * count)[index])
        height = int(data.get("height", [0] * count)[index])
        row = grouped.setdefault(
            key,
            {"parts": [], "left": left, "top": top, "right": left + width, "bottom": top + height, "conf": []},
        )
        row["parts"].append(text)
        row["left"] = min(row["left"], left)
        row["top"] = min(row["top"], top)
        row["right"] = max(row["right"], left + width)
        row["bottom"] = max(row["bottom"], top + height)
        if conf >= 0:
            row["conf"].append(conf / 100.0)
    lines = [
        OCRLine(
            text=" ".join(row["parts"]),
            left=row["left"],
            top=row["top"],
            right=row["right"],
            bottom=row["bottom"],
            confidence=mean(row["conf"]) if row["conf"] else 0.0,
        )
        for row in grouped.values()
    ]
    return sorted(lines, key=lambda line: (line.top, line.left))


def _line_score(line: OCRLine, labels: Iterable[str]) -> float:
    line_norm = _norm(line.text)
    if not line_norm:
        return 0.0
    best = 0.0
    for label in labels:
        label_norm = _norm(label)
        if not label_norm:
            continue
        if label_norm in line_norm:
            score = 1.0
        else:
            score = SequenceMatcher(None, label_norm, line_norm).ratio()
            # Candidate/label lines sometimes carry row numbers and other text;
            # token containment is more stable than whole-line similarity then.
            tokens = [_norm(token) for token in re.split(r"\s+", label) if len(_norm(token)) >= 4]
            if tokens:
                score = max(score, sum(token in line_norm for token in tokens) / len(tokens))
        best = max(best, score)
    return best


def _best_line(lines: list[OCRLine], labels: Iterable[str], *, threshold: float = 0.48) -> OCRLine | None:
    scored = [(line, _line_score(line, labels)) for line in lines]
    scored = [item for item in scored if item[1] >= threshold]
    if not scored:
        return None
    return max(scored, key=lambda item: (item[1], item[0].confidence))[0]


def _remove_table_lines(binary):
    cv2 = _cv2()
    height, width = binary.shape[:2]
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 7), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, height // 2)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    lines = cv2.bitwise_or(horizontal, vertical)
    return cv2.bitwise_and(binary, cv2.bitwise_not(lines))


def _crop_variants(crop):
    cv2 = _cv2()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
    gray = cv2.copyMakeBorder(gray, 16, 16, 24, 24, cv2.BORDER_CONSTANT, value=255)
    gray = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.3, tileGridSize=(8, 8)).apply(gray)
    _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        41,
        11,
    )
    cleaned_otsu = _remove_table_lines(otsu)
    cleaned_adaptive = _remove_table_lines(adaptive)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    cleaned_otsu = cv2.morphologyEx(cleaned_otsu, cv2.MORPH_CLOSE, kernel)
    cleaned_adaptive = cv2.morphologyEx(cleaned_adaptive, cv2.MORPH_CLOSE, kernel)
    # Tesseract usually performs better on black text over white, but the raw
    # contrast image is retained because blue/black pen can vanish in one
    # thresholding method while surviving another.
    return [
        clahe,
        cv2.bitwise_not(cleaned_otsu),
        cv2.bitwise_not(cleaned_adaptive),
    ]


def _encode_png(image) -> bytes:
    cv2 = _cv2()
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("unable to encode deskewed numeric crop")
    return encoded.tobytes()


def read_digit_candidates(crop, *, maximum: int | None = None) -> list[OCRCandidate]:
    pytesseract = _tesseract()
    from pytesseract import Output

    observations: list[tuple[int | None, float, str]] = []
    variants = _crop_variants(crop)
    # Three deliberately different passes provide alternatives without the
    # 12-process-per-cell cost of the first prototype. This matters for Ol
    # Kalou (12 numeric rows x 144 streams) and keeps a rebuild comfortably
    # inside the scheduled workflow window.
    passes = (
        (variants[0], "--oem 1 --psm 7 -l eng"),
        (variants[1], "--oem 1 --psm 7 -l eng -c tessedit_char_whitelist=0123456789"),
        (variants[2], "--oem 1 --psm 13 -l eng -c tessedit_char_whitelist=0123456789"),
    )
    for variant, config in passes:
        data = pytesseract.image_to_data(variant, output_type=Output.DICT, config=config)
        texts: list[str] = []
        confs: list[float] = []
        for index, raw in enumerate(data.get("text", [])):
            text = str(raw or "").strip()
            if not text:
                continue
            texts.append(text)
            try:
                conf = float(data.get("conf", ["-1"])[index])
            except (TypeError, ValueError, IndexError):
                conf = -1.0
            if conf >= 0:
                confs.append(conf / 100.0)
        joined = " ".join(texts)
        value = numeric_value(joined, maximum=maximum)
        observations.append((value, mean(confs) if confs else 0.0, joined))
    return _aggregate_candidates(observations)


def _candidate_labels(candidate: dict[str, Any]) -> list[str]:
    name = str(candidate.get("name") or "").strip()
    parts = [part for part in re.split(r"\s+", name) if len(part) >= 4]
    labels = [name, str(candidate.get("abbr") or "")]
    # Do not use the surname as a standalone anchor when a full name has
    # multiple parts. Shared surnames are common and caused both Banissa rows
    # to bind to the same handwritten cell in the old full-page approach.
    if len(parts) >= 2:
        labels.extend(parts[:-1])
    elif parts:
        labels.extend(parts)
    return [label for label in labels if label]


def extract_form35a_numeric_cells(
    page_image: Path,
    candidates: list[dict[str, Any]],
    reference: dict[str, Any] | None,
    *,
    include_crop_bytes: bool = False,
) -> dict[str, Any]:
    """Read handwritten Form 35A numeric cells using printed labels as anchors.

    This deliberately does *not* depend on a fixed ROI file. IEBC scans vary in
    crop, skew and page size, while the printed candidate/control labels are much
    easier for Tesseract to locate than the handwritten values themselves. Once
    a label line is located, only its numeric cell is re-OCR'd using digit-only,
    multi-threshold passes.
    """

    cv2 = _cv2()
    image = cv2.imread(str(page_image))
    if image is None:
        raise ValueError(f"Unable to read rendered page: {page_image}")
    image = _deskew_and_normalize(image)
    lines = _page_lines(image)
    height, width = image.shape[:2]
    maximum = int(reference.get("registered")) if reference and reference.get("registered") is not None else 5000
    fields: dict[str, dict[str, Any]] = {}

    def read_anchored(field: str, labels: list[str], kind: str) -> None:
        line = _best_line(lines, labels)
        if line is None:
            fields[field] = {"value": None, "confidence": 0.0, "candidates": [], "anchor": None}
            return
        pad_y = max(10, int(line.height * 0.9))
        y0 = max(0, line.top - pad_y)
        y1 = min(height, line.bottom + pad_y)
        if kind == "candidate":
            # The candidate tally is the right-hand cell of the candidate row.
            x0 = max(int(width * 0.50), min(int(width * 0.76), line.right + 8))
            x1 = int(width * 0.985)
        else:
            # Polling Station Counts values sit immediately to the right of the
            # printed label, around the middle of the page.
            x0 = max(int(width * 0.34), min(int(width * 0.52), line.right + 6))
            x1 = int(width * 0.66)
        if x1 <= x0 or y1 <= y0:
            fields[field] = {"value": None, "confidence": 0.0, "candidates": [], "anchor": line.text}
            return
        crop = image[y0:y1, x0:x1]
        guesses = read_digit_candidates(crop, maximum=maximum)
        top = guesses[0] if guesses else None
        field_result: dict[str, Any] = {
            "value": top.value if top else None,
            "confidence": top.confidence if top else 0.0,
            "source": "anchored-cell-ocr",
            "candidates": [
                {
                    "value": item.value,
                    "confidence": item.confidence,
                    "observations": item.observations,
                    "raw": list(item.raw),
                    "source": item.source,
                }
                for item in guesses[:4]
            ],
            "anchor": line.text,
            "crop": [x0, y0, x1 - x0, y1 - y0],
        }
        if include_crop_bytes:
            # Private in-memory evidence only. The cloud reader consumes and
            # removes this value before any JSON is written. The bytes are from
            # the same deskewed page used to calculate the coordinates.
            field_result["_crop_png"] = _encode_png(crop)
        fields[field] = field_result

    for candidate in candidates:
        read_anchored(f"candidate_{candidate['id']}", _candidate_labels(candidate), "candidate")

    controls = {
        "registered": ["TOTAL NUMBER OF REGISTERED VOTERS IN THE POLLING STATION", "REGISTERED VOTERS"],
        "rejected": ["TOTAL NUMBER OF REJECTED BALLOT PAPERS", "REJECTED BALLOT PAPERS"],
        "total_valid": ["TOTAL NUMBER OF VALID VOTES CAST", "TOTAL VALID VOTES CAST"],
    }
    for field, labels in controls.items():
        read_anchored(field, labels, "control")

    return {
        "schema": "kenya.election.handwriting-cells.v1",
        "fields": fields,
        "page_size": [width, height],
        "anchors_found": sum(1 for item in fields.values() if item.get("anchor")),
    }


def _option_rows(
    field: str,
    parsed_fields: dict[str, dict[str, Any]],
    cell_fields: dict[str, dict[str, Any]],
    *,
    reference_value: int | None = None,
) -> list[dict[str, Any]]:
    options: dict[int, dict[str, Any]] = {}

    def add(value: Any, confidence: Any, source: str, observations: int = 1) -> None:
        if value is None:
            return
        value = int(value)
        confidence = max(0.0, min(0.99, float(confidence or 0.0)))
        score = confidence + min(0.15, 0.04 * max(0, observations - 1))
        current = options.get(value)
        row = {"value": value, "confidence": confidence, "score": score, "source": source, "observations": observations}
        if current is None or row["score"] > current["score"]:
            options[value] = row

    parsed = parsed_fields.get(field, {})
    add(parsed.get("value"), parsed.get("confidence", 0.0) * 0.72, "full-page-text")
    cell = cell_fields.get(field, {})
    for candidate in cell.get("candidates", [])[:6]:
        add(
            candidate.get("value"),
            candidate.get("confidence"),
            str(candidate.get("source") or "anchored-cell-ocr"),
            int(candidate.get("observations", 1)),
        )
    if reference_value is not None:
        # A register value is a weak hint, never publication authority. Give it
        # enough weight to defeat an obvious row-number hallucination (1/2),
        # but not enough to overwrite a plausible multi-digit reading that may
        # represent a genuine form/reference discrepancy for V07 review.
        observed = [int(value) for value in options]
        obvious_row_number = bool(observed) and max(observed) <= 9 and int(reference_value) >= 100
        add(reference_value, 0.58 if obvious_row_number else 0.28, "certified-register-hint", 1)
    return sorted(options.values(), key=lambda row: (row["score"], row["confidence"]), reverse=True)[:5]


def _best_exact_candidate_sum(
    candidate_options: dict[str, list[dict[str, Any]]],
    target: int,
) -> tuple[dict[str, dict[str, Any]], float] | None:
    # Dynamic programming keeps this tractable for Ol Kalou's nine candidates:
    # target is bounded by registered voters (normally < 1,000), not by the
    # Cartesian product of every OCR alternative.
    states: dict[int, tuple[float, dict[str, dict[str, Any]]]] = {0: (0.0, {})}
    for field, options in candidate_options.items():
        if not options:
            return None
        next_states: dict[int, tuple[float, dict[str, dict[str, Any]]]] = {}
        for subtotal, (score, chosen) in states.items():
            for option in options[:4]:
                new_total = subtotal + int(option["value"])
                if new_total > target:
                    continue
                new_score = score + float(option["score"])
                current = next_states.get(new_total)
                if current is None or new_score > current[0]:
                    next_states[new_total] = (new_score, {**chosen, field: option})
        states = next_states
        if not states:
            return None
    if target not in states:
        return None
    score, chosen = states[target]
    return chosen, score


def reconcile_form35a_fields(
    parsed: dict[str, Any],
    cell_result: dict[str, Any] | None,
    reference: dict[str, Any] | None,
    candidate_ids: list[str],
    *,
    candidate_list_complete: bool = True,
) -> dict[str, Any]:
    """Merge full-page and anchored-cell OCR under Form 35A arithmetic constraints."""

    if not cell_result:
        return parsed
    parsed_fields = parsed.setdefault("fields", {})
    evidence = parsed.setdefault("evidence", {})
    cell_fields = cell_result.get("fields", {})
    registered_reference = (
        int(reference["registered"])
        if reference and reference.get("registered") is not None
        else None
    )

    options_by_field: dict[str, list[dict[str, Any]]] = {}
    for candidate_id in candidate_ids:
        field = f"candidate_{candidate_id}"
        options_by_field[field] = _option_rows(field, parsed_fields, cell_fields)
    options_by_field["registered"] = _option_rows(
        "registered", parsed_fields, cell_fields, reference_value=registered_reference
    )
    for field in ("rejected", "total_valid"):
        options_by_field[field] = _option_rows(field, parsed_fields, cell_fields)

    selected: dict[str, dict[str, Any]] = {}
    # Prefer an exact candidate sum for any plausible total-valid alternative
    # only when the configured candidate roster is known to be complete. A
    # benchmark profile may intentionally begin with only a subset of candidate
    # names while the statutory list/ballot order is still being sourced. In
    # that mode forcing the configured subtotal to equal total valid would make
    # the reconciler "repair" otherwise good handwriting into false numbers.
    total_options = options_by_field["total_valid"]
    candidate_options = {f"candidate_{cid}": options_by_field[f"candidate_{cid}"] for cid in candidate_ids}
    if candidate_list_complete:
        exact_choices: list[tuple[float, int, dict[str, dict[str, Any]], dict[str, Any]]] = []
        for total_option in total_options[:4]:
            target = int(total_option["value"])
            exact = _best_exact_candidate_sum(candidate_options, target)
            if exact:
                choices, score = exact
                exact_choices.append((score + float(total_option["score"]) + 0.45, target, choices, total_option))
        if exact_choices:
            _, _, choices, total_choice = max(exact_choices, key=lambda row: row[0])
            selected.update(choices)
            selected["total_valid"] = total_choice
        else:
            for field, options in candidate_options.items():
                if options:
                    selected[field] = options[0]
            if total_options:
                selected["total_valid"] = total_options[0]
    else:
        for field, options in candidate_options.items():
            if options:
                selected[field] = options[0]
        if total_options:
            selected["total_valid"] = total_options[0]

    for field in ("registered", "rejected"):
        if options_by_field[field]:
            selected[field] = options_by_field[field][0]

    for field, option in selected.items():
        parsed_fields[field] = {
            "value": int(option["value"]),
            "confidence": min(0.99, float(option["confidence"])),
            "source": option["source"],
            "alternatives": options_by_field.get(field, []),
        }
        anchor = cell_fields.get(field, {}).get("anchor")
        evidence[field] = f"{option['source']} anchored by {anchor!r}" if anchor else option["source"]

    # This form layout does not print a separate total-cast row. Derive it from
    # the two independently reviewed controls whenever both are available.
    valid = parsed_fields.get("total_valid", {}).get("value")
    rejected = parsed_fields.get("rejected", {}).get("value")
    if valid is not None and rejected is not None:
        conf = min(
            float(parsed_fields["total_valid"].get("confidence", 0.0)),
            float(parsed_fields["rejected"].get("confidence", 0.0)),
        )
        parsed_fields["total_cast"] = {
            "value": int(valid) + int(rejected),
            "confidence": conf,
            "source": "derived-valid-plus-rejected",
            "alternatives": [],
        }
        evidence["total_cast"] = f"derived: total_valid ({valid}) + rejected ({rejected})"

    parsed["handwriting"] = {
        "schema": cell_result.get("schema"),
        "anchors_found": cell_result.get("anchors_found", 0),
        "page_size": cell_result.get("page_size"),
        "candidate_list_complete": bool(candidate_list_complete),
        "cloud_crop_ocr": cell_result.get("cloud_crop_ocr"),
    }
    return parsed
