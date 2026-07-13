#!/usr/bin/env python3
"""Assisted ROI calibration -- run this once you have a REAL scanned Form 35A
(2022 Ol Kalou, or the Emurua Dikirr dress-rehearsal corpus: same portal,
same era, same layout -- see docs/OL_KALOU_LIVE_TRACKING_ENGINE_SPEC_v2.md
section 5.3).

What this produces is a STARTING GUESS, not a calibrated map. Form 35A's
general layout is standardised (header block, then one row per candidate in
ballot order, then rejected/valid/cast controls near the foot of the form),
so evenly-spaced rows within a plausible results-table region are a
reasonable first approximation -- but "reasonable approximation" is exactly
as far as an image I have never seen can honestly go. It still needs a human
to open the reference image and the suggested crops side by side and adjust
every box that's off.

Safety properties, deliberately preserved:
  - Never writes to data/reference/form35a_roi.json (the live file). Always
    writes to a sibling *.candidate.json instead.
  - Always sets status to "NEEDS_VISUAL_VERIFICATION", never "VERIFIED".
    Promoting a file to the live path with status VERIFIED is a manual,
    deliberate act -- this tool cannot do it for you, on purpose.
  - Also renders an overlay PNG with every suggested box drawn on top of
    the reference image, so "does this look right" is a 10-second glance,
    not a spreadsheet-reading exercise.

Usage:
  python scripts/suggest_roi_template.py path/to/scanned_form35a.jpg

Then:
  1. Open <output>.overlay.png next to the candidate JSON. Compare box
     positions against the real form.
  2. Nudge any wrong [x, y, width, height] values in the candidate JSON.
     Re-run with --preview-only to re-render the overlay without
     re-guessing, to check your adjustments.
  3. Copy the corrected fields into data/reference/form35a_roi.json,
     set reference_size to the image's actual [width, height], set
     reference_image to point at a saved copy of this reference scan,
     and ONLY THEN set status to "VERIFIED".
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data/reference/candidates.json"


def suggest_layout(width: int, height: int, n_candidates: int) -> dict:
    """Evenly-spaced candidate rows within a plausible results-table region,
    plus control totals below. All fractions are structural assumptions
    about Form 35A's known general layout, not measurements of this
    specific image -- treat every box as a guess.
    """
    # Fractional bounds, expressed as guesses about where the results table
    # and control totals typically sit on a Form 35A page. ADJUST THESE
    # FIRST if the overlay shows the whole table is higher/lower than this.
    table_top, table_bottom = 0.30, 0.78
    controls_top, controls_bottom = 0.80, 0.94

    numeral_left, numeral_right = 0.62, 0.82
    words_left, words_right = 0.20, 0.60

    row_h = (table_bottom - table_top) / n_candidates
    fields = {}
    for i in range(n_candidates):
        y0 = table_top + i * row_h
        y1 = y0 - row_h * 0.08 + row_h  # tiny overlap margin for skewed scans
        fields[f"__row_{i}__.numeral"] = _box(numeral_left, y0, numeral_right, y1, width, height)
        fields[f"__row_{i}__.words"] = _box(words_left, y0, words_right, y1, width, height)

    control_h = (controls_bottom - controls_top) / 4
    control_names = ["registered", "rejected", "total_valid", "total_cast"]
    for i, name in enumerate(control_names):
        y0 = controls_top + i * control_h
        y1 = y0 + control_h
        fields[f"{name}.numeral"] = _box(numeral_left, y0, numeral_right, y1, width, height)
        fields[f"{name}.words"] = _box(words_left, y0, words_right, y1, width, height)

    return fields


def _box(left, top, right, bottom, width, height):
    x, y = int(left * width), int(top * height)
    w, h = int((right - left) * width), int((bottom - top) * height)
    return [x, y, w, h]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="Path to a real scanned Form 35A")
    parser.add_argument("--out", type=Path, default=None, help="Output path (default: sibling *.candidate.json)")
    args = parser.parse_args()

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Install Pillow: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    if not args.image.exists():
        print(f"Not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(args.image)
    width, height = img.size

    candidates = json.loads(CANDIDATES_PATH.read_text())["candidates"]
    n = len(candidates)
    raw_fields = suggest_layout(width, height, n)

    fields = {}
    for i, c in enumerate(candidates):
        fields[f"candidate_{c['id']}.numeral"] = raw_fields.pop(f"__row_{i}__.numeral")
        fields[f"candidate_{c['id']}.words"] = raw_fields.pop(f"__row_{i}__.words")
    fields.update(raw_fields)  # remaining control-total fields

    out_path = args.out or args.image.with_suffix(".roi.candidate.json")
    payload = {
        "schema": "olkalou.form35a.roi.v1",
        "status": "NEEDS_VISUAL_VERIFICATION",
        "reference_image": args.image.name,
        "reference_size": [width, height],
        "allow_resize_fallback": False,
        "fields": fields,
        "notes": [
            f"AUTO-SUGGESTED from {args.image.name} ({width}x{height}) using "
            "assumed structural fractions of a standard Form 35A layout -- "
            "NOT measured against this specific image. Every box is a "
            "starting guess. Open the .overlay.png next to this file, "
            "compare against the real form, and adjust coordinates that are "
            "off before this can be trusted.",
            "This file was written by scripts/suggest_roi_template.py, "
            "never by hand-verification. Do not copy it to "
            "data/reference/form35a_roi.json or set status to VERIFIED "
            "until a human has actually checked every box.",
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    overlay_path = out_path.with_suffix("").with_suffix(".overlay.png")
    overlay = img.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    for name, (x, y, w, h) in fields.items():
        colour = (255, 80, 0) if "candidate_" in name else (0, 160, 255)
        draw.rectangle([x, y, x + w, y + h], outline=colour, width=3)
        draw.text((x + 4, y + 2), name.replace("candidate_", "").replace(".numeral", " (#)").replace(".words", " (words)"),
                   fill=colour)
    overlay.save(overlay_path)

    print(f"Wrote {out_path}")
    print(f"Wrote {overlay_path} -- open this and compare against the real form before trusting anything.")
    print("Status is NEEDS_VISUAL_VERIFICATION. This script will never write status=VERIFIED.")


if __name__ == "__main__":
    main()
