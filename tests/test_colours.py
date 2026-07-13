import json
from pathlib import Path


def luminance(hex_colour: str) -> float:
    values = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(left: str, right: str) -> float:
    high, low = sorted((luminance(left), luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_candidate_colours_meet_graphical_contrast():
    root = Path(__file__).parents[1]
    data = json.loads((root / "data/reference/candidates.json").read_text())
    for candidate in data["candidates"]:
        assert contrast(candidate["colour"], "#0E1116") >= 3.0, candidate["id"]
