# OCR per-candidate extraction + provisional (unverified) aggregate

Requested: enhance OCR to extract individual candidate votes by polling
station, and sum these into a provisional/unverified result across all
scanned documents, converging toward the verified total as forms are
confirmed.

Built both halves. The extraction half is a straightforward completion of
existing, already-generic machinery. The aggregation half is real but
deliberately **not public** -- read "Where the line is drawn" before wiring
it into anything else.

## 1. OCR extraction now covers all 9 real candidates

`ocr/cloud.py`'s `merge_engine_outputs()` and `ocr/roi.py`'s `crop_rois()`
were already fully data-driven off `data/reference/form35a_roi.json` --
whatever fields that file names, the pipeline reads. The gap was the file
itself: `"fields": {}`, `status: "UNMAPPED"`. Nothing could be extracted
because nothing was named.

`scripts/build_form35a_roi_template.py` now generates the full field
structure from the real roster in `data/reference/candidates.json`: a
`.numeral` and `.words` cell for each of the 9 actual candidates (UDA, DCP,
JUBILEE, PNU, PDP, KMM, FPK, PRP, NLP -- not placeholders), plus the 4
control totals, plus a Textract Queries list with each candidate's real full
name filled in ("How many votes did Samuel Muchina Nyagah of United
Democratic Alliance receive?"). `extraction_to_stream_result()` in
`extraction.py` already turns any `candidate_*` field into `StreamResult.votes`
-- that part needed no changes at all.

**What is deliberately still missing: real pixel coordinates.** Every field
is the sentinel `[0,0,0,0]`. There is no scanned Form 35A available in this
environment to measure against, and `data/reference/form35a_roi.json`
controls what the OCR pipeline actually reads on election night -- guessing
specific coordinates and asserting they're right would be worse than
leaving them unmapped, not better. Two things keep this failing safely:

- `ocr/preprocess.py`'s `prepare_rois()` refuses to run at all unless
  `status == "VERIFIED"`. The template builder sets `AWAITING_CALIBRATION`.
- `enhanced_crop()` raises loudly on any zero-size crop, so even if `status`
  were changed by hand without fixing the coordinates, it fails immediately
  and obviously rather than silently reading the wrong part of the image.

Confirmed both still hold: `tests/test_provisional.py` and manual checks in
this session re-ran `prepare_rois()` against the rebuilt file and it still
raises `"ROI map is not VERIFIED"`.

`scripts/suggest_roi_template.py` is the calibration path once a real form
exists (2022 Ol Kalou, or the Emurua Dikirr dress-rehearsal corpus -- same
portal, same era, same layout; see
`docs/OL_KALOU_LIVE_TRACKING_ENGINE_SPEC_v2.md` section 5.3). It suggests
evenly-spaced candidate rows within a plausible results-table region --
a structural assumption about Form 35A's known layout, explicitly labelled
as a guess, not a measurement -- and renders an overlay PNG with every box
drawn on the actual image so checking it is a 10-second visual glance. It
always writes to a sibling `*.candidate.json`, never the live path, and
always stamps `status: "NEEDS_VISUAL_VERIFICATION"`. It cannot write
`VERIFIED` under any code path. Promoting a calibrated file to production is
a manual, deliberate act: copy the checked coordinates into
`data/reference/form35a_roi.json`, set `reference_size` to the real image
dimensions, and only then flip `status` by hand.

CI now runs the template builder on every push and asserts the result is
never `VERIFIED` and always has all 26 fields -- so a future change can't
silently regress either the candidate coverage or the safety gate.

## 2. Provisional (unverified) aggregate -- built, kept internal

`src/olkalou_engine/provisional.py` sums whatever OCR has extracted across
*every* stream with a recorded result, regardless of trust state --
including `QUARANTINED` forms that failed a statutory check or haven't been
seen by a human, and `CONFLICTED` forms with disputed figures. This is the
literal opposite discipline of `Publisher.build()`, which only ever counts
`PUBLISHED`/`DISPUTED` streams (spec's "publication rules, non-negotiable" --
now enforced by `tests/test_provisional.py::test_publisher_public_payload_never_contains_provisional_data`,
which builds a form with 999 fabricated-in-the-test votes sitting in
`QUARANTINED` and asserts the public payload's real total is still 0).

Access:
- `GET /api/provisional` on the review console, behind the exact same
  `require_token` auth as everything else (see
  `SYNC_ERROR_DIAGNOSIS_NOTES.md` / `AUDIT_AND_CORRECTIONS_13JUL.md` for why
  that auth is no longer bypassable).
- `python -m olkalou_engine.cli --root . provisional` -- prints the same
  data to an operator's own terminal, banner-wrapped in the warning text.
- A "⚠ PROVISIONAL (QA ONLY)" button in the review console header opens a
  modal styled with a hazard-stripe warning banner and a red border,
  visually unlike every other panel in the app on purpose.

## Where the line is drawn, and why

This module is **not** wired into `publisher.py`, **not** written to
anything under `data/public/`, and **not** rendered on `index.html` or
`archive.html`. That's a deliberate choice, not an oversight, for one
concrete reason: a raw sum of unverified, uncross-checked OCR reads is
*exactly* what the rest of this codebase exists to keep away from anything
published. Every notes file in this repo says some version of the same
thing -- "OCR remains review-only," "no candidate total is published until
human verification and statutory validation pass" -- because a number that
looks like a result, even captioned "unverified," is a real risk once it
leaves an authenticated operator tool during a live, contested by-election.
Screenshots travel without their caption; a wrong early number in a
constituency where campaign vehicles have already been vandalised (see
`docs/OL_KALOU_LIVE_TRACKING_ENGINE_SPEC_v2.md` section 2.3/16) is not a
hypothetical risk.

If the goal is a genuinely public "quick count," that's a legitimate thing
some election-monitoring bodies do -- but it's normally done with sampling
methodology, a named accountable organisation, and release procedures
designed around exactly this risk, not a live-updating raw sum behind no
door at all. If that's what's wanted here, it should be a deliberate
addition with its own review, not a byproduct of wiring `provisional.py`
into the public payload. Everything needed to change that decision is
narrowly in one place (`provisional.py`'s docstring says the same thing) --
it was kept out on purpose, and it's your call to put it in.

## Validation

- 72 pytest tests passed (63 prior + 9 new: 7 in `test_provisional.py`, 2
  added to `test_review_api_auth.py` for the new endpoint).
- Ruff clean.
- `check-reference` still correctly exits 1 -- nothing here touches the
  reference-completeness gate.
- Confirmed manually: `prepare_rois()` still refuses to run against the
  rebuilt (structurally complete, coordinate-sentinel) ROI file.
- Confirmed manually: `scripts/suggest_roi_template.py` run against a
  synthetic test image produces a correctly-labelled candidate file, a
  readable overlay PNG, and leaves the live ROI file untouched.
