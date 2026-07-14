# OCR accuracy, matching gaps, and the confirm/tally workflow

Requested after reviewing real screenshots of the deployed archive dashboard
against actual scanned Banissa forms: why handwriting OCR is "very off,"
why not all PDFs uploaded, and a save/confirm/tally workflow for the review
card -- applied to Ol Kalou too, ahead of Thursday.

Everything below was found by reading the real screenshots precisely (the
actual printed form text, the actual portal labelling convention) rather
than guessing -- several of these bugs existed specifically because earlier
code (including some of my own, from earlier this session) was tested
against idealized text that happened to match its own assumptions.

## 1. "Not all PDFs uploaded" — two real matching bugs, not a slow pipeline

**34 of Banissa's 81 streams share a station name with at least one other
stream** (computed directly from `streams.json`) — "Banisa Primary School"
alone has 5. `portal_unmatched` showed 35. That's a near-exact match, and a
strong signal about where to look.

`_match_form()` (archive.py) disambiguates a repeated station name by
looking for a "STREAM N" / "STRM N" / "S N" keyword in the portal's link
text. But the real IEBC portal convention — confirmed directly from the
very first screenshots reviewed this session — numbers repeated centres as
a bare trailing suffix with no keyword at all: **"BANISA PRIMARY SCHOOL
01"**, **"...02"**. The keyword search could never match this, so every
multi-stream station was structurally unable to disambiguate.

**Fix:** added a third disambiguation tier, tried only after the existing
keyword check fails, that reads the last 1-2 digit number directly out of
the label — deliberately scoped to `source_label` only, never `source_url`
(a download URL routinely carries unrelated numeric IDs -- page ids,
timestamps -- that must never be used to pick a stream). Tested against the
real convention: `_match_form(bundle, "BANISA PRIMARY SCHOOL 03", url)`
now correctly resolves stream 3, and a test confirms a stray digit in the
URL alone is never enough to produce a match.

The analogous check inside OCR itself (`match_stream()` in
`historical_ocr.py`, which reads the scanned page's own text rather than
the portal label) had the same keyword assumption — but the real printed
form header reads **"OGONDICHO PRIMARY SCHOOL POLLING STATION 2 of 2"**,
never "Stream 2" (read directly off a real scanned form in the review).
Added a second pattern for "POLLING STATION X of Y" specifically.

## 2. Handwriting accuracy — one pure bug, one real limitation, one critical gap

Looked at three real OCR extractions with their source scans open side by
side:

**A pure label bug, unrelated to handwriting quality at all.** `rejected`
was never extracted from a single real form, regardless of OCR accuracy,
because the label list ("REJECTED BALLOTS") never matched what the form
actually prints: **"Total Number of Rejected Ballot Papers"** (no trailing
S on BALLOT, plus "PAPERS"). Fixed the label list to match the real text.
Also: this Form 35A layout has **no explicit "total votes cast" field at
all** (confirmed against the real form -- Registered / Rejected /
Rejection-objections / Disputed / Valid are the only five counted rows) --
`total_cast` now derives from `total_valid + rejected` when the form has no
line for it, instead of staying permanently blank.

**A real limitation, and the actual accuracy problem.** Comparing OCR
output to the real handwriting: `registered` (clean handwriting in a
dedicated box) read correctly about half the time (672, 483) and badly
wrong the other half (7 instead of 673) -- and candidate vote counts,
handwritten less legibly, were wrong almost every time (137 read as 1, 116
read as 72). This is a genuine handwriting-recognition weakness, not a code
bug, and the specific engine in use explains it precisely --

**...which is the third, most consequential finding.** `_engine_set()`'s
`"auto"` mode -- the configured default (`election.json`:
`default_engine: "auto"`) -- was grouped with `"tesseract"`/`"local"` and
meant **Tesseract only, always**, regardless of whether real GCV/AWS
credentials were configured. Tesseract is tuned for printed text and is
well known to be weak specifically at handwritten digits -- exactly the
accuracy pattern observed. Google Cloud Vision's handwriting recognition is
substantially stronger and was never actually being tried.

**Fix:** `"auto"` now tries GCV (if `GCV_CREDENTIALS_JSON` is configured)
and Textract (if `AWS_ACCESS_KEY_ID` is present) first, falling back to
Tesseract only if neither is usable -- and never crashes the run if a
configured cloud engine fails to construct (bad/expired credentials,
package not installed), it just logs a warning and moves on.

**But even a correctly-configured GCV credential would have silently done
nothing**, because `google-cloud-vision`/`boto3` were only ever listed
under the `[ocr]` extra, and `sync-historical-forms.yml` installs
`[historical-ocr,pdf]` -- which never included them. Added both packages
directly to `historical-ocr`'s own extra list (confirmed with a `pip
install --dry-run` that they now resolve).

**Action needed from you, not fixable from here:** the single highest-
leverage remaining step is setting the `GCV_SERVICE_ACCOUNT_JSON` repository
secret on GitHub (the workflow already reads it correctly -- see
`RACE_CONDITION_FIX_NOTES.md`'s earlier review of this same workflow -- the
wiring was already complete, it just had nothing to pass through). Once
that secret exists, the next sync run will use GCV automatically -- no
further code change needed.

## 3. The same class of gap, found on the Ol Kalou side too — one of them critical

Asked to check the equivalent gaps on Ol Kalou's live pipeline before
Thursday. Two are structurally different (Ol Kalou's `dual-cloud` mode
always uses both GCV+Textract together, no silent single-engine "auto"
fallback like Banissa had), but two real gaps existed anyway:

**Critical: `Dockerfile` only installed `[s3]`, never `[ocr]`.** This one
image builds all four `docker-compose` services, including `worker` -- the
actual 60-second live OCR pipeline. `build_extractor()` is called exactly
once, inside `Worker.__init__`. If `OCR_MODE=dual-cloud` is ever turned on
(the natural next step once the ROI map is calibrated) without this fix,
`DualCloudExtractor`'s constructor would hit an `ImportError` for a missing
package **and the entire live worker would fail to start** -- not
gracefully skip OCR, fail to start at all, on election night. Fixed the
Dockerfile to install `[ocr]` (which already includes what `[s3]` needs).

**Also fixed regardless of the Dockerfile issue:** `build_extractor()`
itself had no fallback -- *any* dual-cloud construction failure (missing
package, expired credentials, unreachable API, not just the Dockerfile gap)
crashed worker startup outright. Now catches the failure, logs it loudly,
and falls back to `NoOpExtractor` -- OCR pre-fill is lost for that run, but
the worker starts and every form still goes through manual double-entry
review, exactly the "review console is the product, OCR is the
optimisation" principle this whole project has been built around. This has
zero test coverage before this pass (`build_extractor` was entirely
untested) -- `tests/test_extraction.py` now covers both the fallback (run
for real: `google-cloud-vision` genuinely isn't installed in this build
environment, so this exercises the actual failure path, not a mock) and the
success path (mocked, so it's verified independent of whether the real SDK
happens to be installed wherever this runs next).

I did not attempt to build a Banissa-style label-proximity fallback for Ol
Kalou's own OCR. The Banissa fixes above were only possible because real
screenshots showed the actual printed form text -- I have no equivalent
evidence for Ol Kalou's Form 35A layout, and guessing label text for a form
I've never seen is exactly the mistake this whole investigation just found
and corrected. Safer to leave Ol Kalou's ROI-based ROI-or-nothing design as
is (see `OCR_EXTRACTION_AND_PROVISIONAL_TOTALS_NOTES.md`) than repeat that
pattern blind.

## 4. Save & mark reviewed, green cells, and a tally — both sides

**Archive dashboard (Banissa, and any future historical election).** The
review workbench modal already auto-saved every keystroke as a draft; added
an explicit **"Save & mark reviewed"** button on top of that. Clicking it:

- stamps `confirmed_at` on the draft (editing afterwards keeps it confirmed
  -- a correction doesn't silently un-confirm a stream),
- turns that stream's grid cell a flat green (`.locally-confirmed`),
  visually distinct from `PUBLISHED`'s candidate-coloured fill so it's
  never mistaken for an actually-imported, verified result,
- updates a new tally banner near the top of the page -- "N / 81 streams
  you've confirmed in this browser — UDA 1,204 · UPA 87" -- carrying the
  exact same "not an official result" discipline as the rest of the
  workbench, since a random visitor would only ever see their *own* typed
  totals reflected back, not anyone else's,
- **auto-advances to the next unconfirmed stream**, so reviewing 81 (or
  144) streams doesn't mean hunting through the grid after every save.

**Ol Kalou review console.** Already had a real "Confirm" action (the
existing double-entry `/api/submit` flow) -- what it lacked was visibility.
Added a tally strip under the header, backed by the `/api/provisional`
endpoint already built two sessions ago: "N / 144 streams confirmed —
UDA 1,204 · DCP 340 · ..." refreshed on load and after every submission.
Reuses existing, already-tested infrastructure rather than building a
second parallel system.

## Validation

- 107 pytest tests (92 before this pass; +7 real-form-text regression tests
  in `test_historical_ocr.py`, +4 `auto`-mode selection tests, +4
  `build_extractor` fail-safe tests in the new `tests/test_extraction.py`).
  Ruff clean, `python -m compileall` clean.
- Confirmed with `pip install --dry-run -e '.[historical-ocr,pdf]'` that
  `google-cloud-vision`/`boto3` now actually resolve.
- `tests/frontend/test_review_workbench.js`: extended to 25 assertions,
  covering the full confirm → green cell → tally → auto-advance → CSV
  export path with real DOM events, plus confirming an edit after "Save &
  mark reviewed" doesn't clear the confirmation.
- `node --check` on all four frontend JS surfaces (`app.js`, `archive.js`,
  `config.js`, `review_console/index.html`'s embedded script).
- `build_extractor`'s fallback test genuinely exercises the missing-package
  path (not mocked) since `google-cloud-vision` is absent from this build
  environment -- the same condition the Dockerfile bug caused in
  production before it was fixed.
