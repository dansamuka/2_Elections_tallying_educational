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

## Validation (Ol Kalou side)

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

## 3. The same, for Banissa (and any future historical election)

Banissa's architecture is genuinely different from Ol Kalou's, not just a
smaller version of it -- worth being explicit about before saying "the
same" applies.

**Extraction was already real here.** Unlike Ol Kalou's empty ROI map,
`historical_ocr.py`'s `parse_form35a()`/`parse_form35b()` already do
per-candidate extraction for both of Banissa's real candidates (Hassan
Ahmed Maalim/UDA, Mohamed Nurdin Maalim/UPA) via label-proximity text
search (`_extract_number_near_labels`) rather than ROI cropping -- a
reasonable approach for the embedded-PDF-text/Tesseract engines this
pipeline uses, since there's no calibrated spatial template needed. It
already has ballot-order-independent label matching (full name, then party
abbreviation, then given names, surname last -- deliberately ordered to
avoid binding the wrong candidate row when relatives share a surname) and
already computes V01/V02/V03/V07 per extraction. This needed no
"build the structure" work -- it just needed the actual 81 documents, which
this environment cannot fetch (no network route to iebc.or.ke from this
sandbox; the real ingestion runs via `sync-historical-forms.yml` on GitHub
Actions, which does have network access). `data/elections/banissa-2025/ocr/`
correctly shows zero documents because none have been ingested yet, not
because anything is broken.

**The provisional aggregate has a different risk shape, not a lower one.**
Banissa's election is over and gazetted (10,431 / 1,240, certified). There's
no "who's ahead" narrative this could prematurely feed -- but there's a
different real risk: this module exists specifically to reconcile scanned
Form 35A sums against that declaration, and a raw OCR sum that disagrees
with 10,431 is exactly the kind of thing that gets misread as "the result
was wrong" when it's actually one misread digit on one form. Undermining
confidence in an already-legitimate, certified result is a real harm too.
Same conclusion, different reason: kept internal.

`src/olkalou_engine/historical_provisional.py` sums whichever figure is
best available per stream -- a verified, statutory-checks-passed result if
`import_verified_results()` has run for that stream, otherwise the raw OCR
figure if one exists, otherwise the stream is simply absent from the sum
(same "absent, not zero-filled" discipline as the live version). It also
surfaces the certified Gazette total alongside, explicitly labelled
"reference only, not derived from the sum" -- so an operator sees both
numbers and the difference between them at a glance, without either number
contaminating the other.

Access, deliberately mirroring the live-election pattern exactly:
- `python -m olkalou_engine.cli --root . archive-provisional banissa-2025`
- `GET /api/historical-provisional/{election_id}` -- same `require_token`
  auth, same review console, a second "⚠ BANISSA PROVISIONAL (QA)" button
  next to the Ol Kalou one, reusing the same warning-striped modal.

`build_archive_payload()` (archive.py) is untouched. It already had this
separation right -- `ocr_by_stream` was already loaded and used for
per-stream STATUS display (`"state": "OCR_REVIEW"`) but its vote values
never reached `candidate_totals` or a stream's public `votes` field; only
`verified_results.json` does. `historical_provisional.py` reads the same
source files purely to produce the operator-facing sum and is never called
from `archive.py`.

**What I did not add:** a words-vs-numerals cross-check for the
label-proximity extractor, even though the live pipeline's `words.py` has
one already built and tested. Text-based extraction doesn't have a spatial
ROI to anchor "the words version is near the numeral" the way the live
pipeline's cropped cells do -- doing this well would mean a new
nearby-line-search heuristic, untested against any real document, which is
exactly the kind of speculative change I've been avoiding elsewhere in this
pass (see the ROI-coordinate reasoning above). Worth doing once real
Banissa documents are actually ingested and there's something real to
validate it against -- not blind.

## Validation (Banissa side)

- `tests/test_historical_provisional.py`: 6 tests -- zero-extraction case,
  OCR-only figures counting even when QUARANTINED, verified results taking
  precedence over conflicting OCR for the same stream, the official
  declaration surfacing for reference without contaminating the sum, the
  warning always present, and the same public-payload-never-contaminated
  regression lock as the live version (built a form with 777/1 fabricated
  OCR votes sitting OCR-only, asserted `build_archive_payload`'s real total
  is still the certified 11,671, and that stream's public `votes` is `{}`).
- `tests/test_review_api_auth.py` extended: 3 more tests for
  `/api/historical-provisional/{id}` -- requires auth, works with the
  correct token, 404s on an unconfigured election id.
- Manually confirmed: `archive-provisional banissa-2025` runs cleanly
  against the real bundle (0 contributing streams, matching the honest
  zero-documents state).
- `tests/test_historical_ocr.py` and `tests/test_archive.py` (pre-existing,
  untouched) still pass -- nothing in this pass modified `historical_ocr.py`
  or `archive.py`.

