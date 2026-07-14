# Archive dashboard review: the "why isn't this 100%" bug, and a review workbench

Requested after reviewing the live Banissa archive page and the real IEBC
portal side by side: explain why the dashboard doesn't show 100% when IEBC's
own portal does, and give the per-stream card a real list of candidate OCR
figures, or a way to fill them in from the source PDF.

## 1. Why the page wasn't at 100% -- a real bug, not just a slow pipeline

Two things were actually wrong, both in `frontend/archive.js`, found by
reading the code precisely against the screenshots rather than guessing.

**The headline stat was inflated.** `FORMS ARCHIVED` at the top of the page
computed `Math.max(archive.forms_archived, archive.portal_downloaded)` --
so once all 81 files were *downloaded* (which happened, matching IEBC's own
100%), the top of the page showed 81/81 regardless of how many of those
downloads had actually been recognized as a specific polling stream's form.
Scroll down to the readiness list and the same underlying number
(`archive.forms_archived`, honestly, 72) told a different story. Two
numbers, same label, different values, on the same page. Fixed: the top
stat now shows the same honest number everywhere. No more discrepancy to
notice and ask about.

**A real off-by-itself bug.** `"Source documents inventoried", ocr.documents_total || 0, ocr.documents_total || 0`
-- the denominator was the same field as the numerator. That row could
never show anything but 100%, regardless of how many documents were
actually expected. This is almost certainly the second half of what made
"72" read as "fine" at a glance in the screenshot -- the row sitting right
above it said 72/72. Fixed to compare against `forms_expected`.

**What was already correct and just needed surfacing.** `archive.py` was
already computing `portal_unmatched` (downloads that couldn't be matched to
a stream at the portal stage) -- it just wasn't rendered anywhere. Same for
the gap between `ocr.documents_total` and `ocr.streams_matched` (documents
OCR successfully read but couldn't confidently match to a specific stream
from the scanned text). Both are now shown in the readiness list, and a new
banner (`renderGapNote`) appears automatically whenever `forms_archived <
forms_expected`, walking through the funnel -- portal → downloaded →
recognized as a document → matched to a stream -- so the gap explains
itself on the page instead of needing to be asked about each time.

None of this required backend changes; `archive.py` was already computing
the right numbers, `archive.js` just wasn't showing them faithfully. Fixed
entirely in the frontend.

## 2. The review workbench: OCR figures per stream, and a way to correct them

**Backend (`archive.py`).** `build_archive_payload()` already loaded every
stream's raw OCR extraction (`ocr_by_stream`) to decide its *status*
(`OCR_REVIEW` vs `ARCHIVED` vs `REFERENCE_ONLY`) -- it just never carried
the actual per-candidate numbers into the public payload. Added
`_ocr_prefill()`: pulls `candidate_{id}.value` plus registered/rejected/
total_valid/total_cast straight from the same extraction record, and
attaches it as `stream.ocr.prefill`. Deliberately namespaced under `ocr`,
never under `stream.votes` -- `votes` stays reserved for statutorily-
checked, human-reviewed figures exactly as before (see
`tests/test_archive.py::test_stream_payload_surfaces_ocr_prefill_without_touching_verified_votes`,
which asserts this explicitly).

**Is this safe to show publicly?** Different question from the provisional-
aggregate one two sessions ago, and a different answer. A rolled-up
constituency total built from unverified OCR reads (what stayed gated) is a
"here's basically the result" claim. A single stream's own OCR reading,
individually labelled, sitting next to a link to its own source scan, is
the opposite -- it's exactly the granular, source-linked evidence this
whole project's transparency thesis is built on ("every number is one click
from the scanned form it came from"). This page was already publishing
confidence and route (`QUARANTINE`, `43.1%`) per stream before this change;
showing the actual figures alongside is a natural extension of that
existing disclosure, not a new category of risk. Every figure keeps its
provenance and status attached -- nothing here is presented as a result.

**Frontend (`archive.js`'s `openStream()`).** Rewritten with two paths:

- A `PUBLISHED` (already independently verified) stream renders exactly as
  before -- read-only, no editing needed, nothing to review.
- Anything else opens a genuine review workbench: the scanned Form 35A
  embedded directly in an iframe (the `.dialog-grid`/`.form-frame` CSS was
  already in the stylesheet, unused until now), OCR statutory-check badges
  (V01/V02/V03/V07, previously computed but not shown), and editable
  inputs for every candidate plus registered/rejected/valid/cast --
  pre-filled from the OCR reading, or from a previously-saved draft if one
  exists.

**"At least I should be able to fill in from the PDF"** -- this is a static
GitHub Pages site with no backend to receive a submission, so typing a
correction can't publish anything by itself (nor should it: that would
bypass every statutory check `import_verified_results()` enforces). What it
does instead: every edit auto-saves to this browser's `localStorage`,
scoped per election. A "Download review draft CSV" button in the page
toolbar assembles every drafted stream into a CSV with the *exact* column
order `import_verified_results()` requires -- download it, hand it to
`archive-import banissa-2025 <file>.csv`, and it goes through the real,
unchanged, statutorily-gated verification path. This tool prepares the
input; it never substitutes for the gate.

A per-stream "Copy this row as CSV" button is also there for pasting a
single correction directly into a spreadsheet without downloading the whole
batch.

## Validation

- `tests/test_archive.py`: 6 new tests (11 total in the file) --
  `_ocr_prefill()` extracts votes and controls correctly, omits candidates
  the parser didn't read (never zero-fills), returns `None` for an absent
  or empty extraction; a stream with a real OCR record surfaces
  `ocr.prefill` while `votes` stays untouched and constituency totals stay
  exactly the certified 11,671; a stream with no OCR record at all gets
  `ocr: null`; `forms_archived` stays honest against `forms_expected`
  rather than getting inflated. 92 pytest tests pass overall (86 prior + 6
  new), ruff clean.
- `tests/frontend/test_review_workbench.js` (new): loads the *real*
  `archive.html`/`archive.js`/`config.js` into jsdom against a realistic
  synthetic payload and drives them through actual DOM events -- not a
  syntax check, not a reimplementation of the logic under test. 22
  assertions, all passing, including: the FORMS ARCHIVED fix (asserts
  `3/4`, not an inflated max), the "Source documents inventoried" fix
  (asserts it's compared against the expected total, not itself), the gap
  note renders and explains the funnel, OCR prefill values appear in the
  right inputs, editing one candidate's figure persists to `localStorage`
  while leaving the other candidate's OCR value intact, re-opening a stream
  shows the saved correction rather than the original OCR reading, a
  `PUBLISHED` stream shows no editable inputs, a stream with no OCR record
  doesn't crash, and the exported CSV has the exact real column order and
  contains corrections rather than raw OCR values. Caught one real bug
  during development (a missing `process.exit()` left archive.js's own
  60-second auto-refresh timer keeping the test process alive forever) --
  fixed, documented in the test file itself.
- `node --check` on all three frontend JS files still passes.
- Regenerated the real Banissa payload through the modified
  `build_archive_payload()` against the actual reference data (no crash,
  correct shape; `ocr: null` throughout since this environment has no real
  OCR extraction files locally -- that only exists on the deployed
  instance after a real sync).
- Wired `tests/frontend`'s suite into `ci.yml`, right after the existing
  `node --check` steps.
