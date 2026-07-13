#!/usr/bin/env python3
"""Builds the FIELD STRUCTURE of data/reference/form35a_roi.json from the
real 9-candidate roster in data/reference/candidates.json.

What this script does NOT do, on purpose: it does not invent pixel
coordinates. There is no real scanned Form 35A available to measure against
in this environment. Every coordinate is the sentinel [0,0,0,0] ("zero-size
crop" -- the same convention the repo's own form35a_roi.example.json already
uses to mean "not a real value"). ocr/preprocess.py's enhanced_crop() raises
loudly on a zero-size crop, and prepare_rois() separately refuses to run
unless status == "VERIFIED" -- this script deliberately sets status to
AWAITING_CALIBRATION, not VERIFIED, so both safety checks stay engaged.

What DOES get built correctly: every one of the 9 real candidates (by their
actual id/name from candidates.json, not a placeholder), a numeral + words
cell for each, the four control totals, and a Textract Queries list with the
real candidate names filled in -- all of which is genuine, checkable
structure that the rest of the pipeline (merge_engine_outputs in ocr/cloud.py
is already fully data-driven off this file) will use correctly the moment
real coordinates replace the sentinels.

Usage: python scripts/build_form35a_roi_template.py
Then: measure real coordinates (see scripts/suggest_roi_template.py for an
assisted starting guess once you have an actual scanned form), replace the
sentinels, and only then set status to VERIFIED.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data/reference/candidates.json"
ROI_PATH = ROOT / "data/reference/form35a_roi.json"

SENTINEL = [0, 0, 0, 0]  # invalid on purpose -- see module docstring

CONTROL_FIELDS = ["registered", "rejected", "total_valid", "total_cast"]


def build():
    candidates = json.loads(CANDIDATES_PATH.read_text())["candidates"]

    fields = {}
    textract_queries = []
    for c in candidates:
        cid = c["id"]
        fields[f"candidate_{cid}.numeral"] = SENTINEL
        fields[f"candidate_{cid}.words"] = SENTINEL
        textract_queries.append({
            "Text": f"How many votes did {c['name']} of {c['party']} receive?",
            "Alias": f"candidate_{cid}.numeral",
        })

    for field in CONTROL_FIELDS:
        fields[f"{field}.numeral"] = SENTINEL
        fields[f"{field}.words"] = SENTINEL

    control_queries = {
        "registered": "How many registered voters does this polling station have?",
        "rejected": "How many rejected votes were recorded?",
        "total_valid": "What is the total number of valid votes?",
        "total_cast": "What is the total number of votes cast?",
    }
    for field, question in control_queries.items():
        textract_queries.append({"Text": question, "Alias": f"{field}.numeral"})

    payload = {
        "schema": "olkalou.form35a.roi.v1",
        "status": "AWAITING_CALIBRATION",
        "reference_image": "form35a-reference.png",
        "reference_size": None,
        "allow_resize_fallback": False,
        "fields": fields,
        "textract_queries": textract_queries,
        "candidate_field_map": {c["id"]: c["name"] for c in candidates},
        "notes": [
            "Field NAMES below are real (all 9 actual Ol Kalou candidates, "
            "from data/reference/candidates.json). Every COORDINATE is the "
            "sentinel [0,0,0,0] -- deliberately invalid, not measured. "
            "ocr/preprocess.py's enhanced_crop() raises on a zero-size crop, "
            "and prepare_rois() separately refuses to run unless "
            "status == 'VERIFIED'. Both stay engaged with this file as-is.",
            "To calibrate: get a real scanned Form 35A (2022 Ol Kalou, or "
            "the Emurua Dikirr dress-rehearsal corpus -- same portal, same "
            "era, same layout), set reference_size to its [width, height], "
            "and either measure each field's [x,y,width,height] by hand in "
            "an image editor, or run scripts/suggest_roi_template.py for an "
            "assisted starting guess that still requires visual "
            "verification before it can be trusted.",
            "Do not set status to VERIFIED until every coordinate has "
            "actually been checked against the real form. This file "
            "controls what the OCR pipeline reads on election night.",
        ],
    }

    ROI_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {ROI_PATH.relative_to(ROOT)}: {len(candidates)} candidates, "
          f"{len(fields)} fields, status={payload['status']} (NOT VERIFIED, coordinates are sentinels)")


if __name__ == "__main__":
    build()
