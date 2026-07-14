# Kenya Election Tallying Wall

Ol Kalou live engine v2 + reusable historical-election archive and replay module.

A provenance-first implementation of the Ol Kalou parliamentary by-election tracking specification. The system archives every IEBC-published result form immutably, routes untrusted extraction through statutory checks and independent human review, publishes only gated figures, and makes every public number traceable to its source form.

> **UNOFFICIAL — Independent parallel tally compiled from IEBC-published Form 35A scans. Only the Returning Officer may declare the result of this election.**

## One-click GitHub publishing

On Windows, extract the ZIP and double-click:

```bat
PUSH_TO_GITHUB.cmd
```

The script checks or installs Git and GitHub CLI, opens secure browser login when necessary, runs the test suite, regenerates the public datasets, reconnects to `dansamuka/2_Elections_tallying_educational`, replaces changed files on `main`, and enables the GitHub Pages workflow. It refuses to create a different repository.

The deployed site exposes:

- `/` — Ol Kalou live tallying wall.
- `/archive.html` — previous-polls module.
- `/methodology.html` — public methods and trust rules.

See `GITHUB_ONE_CLICK_GUIDE.md` for the exact flow.

## What is implemented

- 60-second watcher with conditional requests, backoff, structural canary and manifest.
- Immutable SHA-256 form archive with versioned metadata and optional R2/S3 mirroring.
- Five-minute IEBC portal synchronization through GitHub Actions, plus a secure manual workflow and Windows one-click trigger. New links are discovered across paginated constituency pages, forms are downloaded immutably, and only meaningful changes are committed and redeployed.
- Historical document OCR that recursively inventories portal downloads and PDF/image uploads, hashes and mirrors originals, classifies Form 35A/35B pages, generates a statutory-check review queue, and never auto-publishes.
- Optional Google Vision + AWS Textract ROI/Queries consensus adapter; local Tesseract and embedded-PDF extraction are available for historical pre-fill.
- V01–V12 validation framework and a hard publication gate.
- Keyboard-driven double-entry review console with explicit third-person adjudication.
- Immutable amended-form versions, conflict detection, anomaly feed and append-only corrections ledger.
- `live.json` publisher with monotonic sequence protection, worker-specific objects and last-writer safety.
- T1/T2 outstanding-vote bounds, ward-stratified Monte Carlo projection and bloc arithmetic.
- Mobile-first static dashboard with the 144-cell Stream Grid, stale-feed warnings, last-known-good cache, form links, stream table and public correction log.
- Form 35B reconciliation command and Markdown report generator.
- Reference-data importers that refuse to certify anything except exactly 144 rows summing to the official register total.


## Ol Kalou five-minute hierarchy sync

The same scheduled and manual portal engine now covers the live Ol Kalou 2026 profile, Banissa and the Malava OCR-validation benchmark. Ol Kalou follows `KENYA → NYANDARUA → OL KALOU → ward → polling centre → polling stream`, accepts only the individual cloud-download action, and expects 144 Form 35As across Rurii (33), Kanjuiri Range (32), Karau (27), Kaimbaga (27), and Mirangine (25).

```bat
UPDATE_OL_KALOU_NOW.cmd
```

The Ol Kalou archive/OCR payload is deliberately reference-gated. Forms may be archived and OCR-prefilled, but no OCR number is automatically published while the certified atomic register or final ballot/Form 35A order remains unresolved.

## Previous-polls module

Historical contests use the same provenance model without contaminating the live Ol Kalou state. Each election is a self-contained folder under `data/elections/<election-id>/` with:

- `election.json` — contest, candidates, official declaration and source notes;
- `streams.json` — the complete certified polling-stream register;
- `results_template.csv` — independent Form 35A transcription frame;
- optional immutable archived forms and `verified_results.json`.

Banissa 2025 is included as the first profile. Its 81-stream, 32,703-voter register and declared constituency totals are visible immediately. Stream-by-stream replay remains withheld until all 81 Form 35As and genuine reporting timestamps have been archived and independently entered.

Malava 2025 is included as a deliberately non-publishable handwriting benchmark. The IEBC portal reports 198 Form 35A assignments. The first sync bootstraps a complete review-only matching roster only if all 198 assignments are present; partial discovery is rejected. Human-confirmed rows turn green, feed the benchmark panel and can be exported to `scripts/measure_historical_ocr_accuracy.py`. See `docs/MALAVA_OCR_VALIDATION.md`.

Place every available Banissa PDF/image under `data/elections/banissa-2025/documents/`, then double-click `RUN_HISTORICAL_OCR.cmd`. The OCR pass scans every page, collapses exact duplicates, creates immutable public source mirrors, and writes `data/elections/banissa-2025/ocr/review_queue.csv`. No OCR value enters the tally until two-person review and `archive-import` validation.

```bash
# Inventory all historical source documents
python -m olkalou_engine.cli --root . archive-documents banissa-2025

# OCR all eligible files into a human review queue
python -m olkalou_engine.cli --root . archive-ocr banissa-2025 --engine auto

# List configured historical elections and rebuild the website catalog
python -m olkalou_engine.cli --root . archive-list

# Discover and archive Banissa Form 35As from the configured IEBC portal
python -m olkalou_engine.cli --root . archive-run banissa-2025

# Import independently checked stream figures
python -m olkalou_engine.cli --root . archive-import banissa-2025 \
  data/elections/banissa-2025/results_template.csv

# Rebuild the public payload without network access
python -m olkalou_engine.cli --root . archive-build banissa-2025
```

The importer enforces candidate-sum, cast-total, turnout and official-register checks before accepting a stream. The replay control switches on only when every stream has a verified result and a real timestamp.

### Automatic IEBC portal updates

The repository includes `.github/workflows/sync-historical-forms.yml`. It checks the configured IEBC result-form portal every five minutes and can also be run manually. For each enabled election it:

1. reads the constituency row and reported-form count;
2. follows the constituency detail page and every Yii pagination page;
3. downloads all newly discovered Form 35A/35B files into immutable, SHA-256-versioned paths;
4. inventories PDFs/images and runs embedded-text extraction or Tesseract OCR;
5. writes the OCR review queue and rebuilds the archive dashboard;
6. commits and deploys only when files, extraction records, or status meaningfully change.

The public archive's **Update now** button opens the repository-owner GitHub Actions screen. GitHub requires an authenticated user with write access to press **Run workflow**. From Windows, `UPDATE_IEBC_FORMS_NOW.cmd` triggers the same workflow directly through GitHub CLI.

```bash
# Full portal download → OCR → dashboard refresh for Banissa
python -m olkalou_engine.cli --root . archive-sync banissa-2025 --engine auto

# Malava 198-form OCR benchmark
python -m olkalou_engine.cli --root . archive-sync malava-2025 --engine auto

# Process every election enabled in data/elections/sync.json
python -m olkalou_engine.cli --root . archive-sync --all --engine auto
```

OCR remains a pre-fill. The automated workflow updates form coverage and the review queue, but candidate figures do not enter the verified historical tally until the existing independent-review and statutory-validation gate is completed. See `docs/AUTOMATED_IEBC_SYNC.md`.

### Add another previous poll

Copy `data/elections/banissa-2025` to a new election ID, replace the profile and certified stream rows, then run `archive-build`. No frontend code change is required; the catalog discovers every valid election folder automatically. See `docs/ADDING_PREVIOUS_POLL.md` for the field-by-field guide.

## Production safety state

The repository intentionally ships with **unresolved atomic polling rows and provisional ballot ordering**. Current public official information gives 144 expected polling units and 73,480 registered voters, but the production worker will not start until the certified 144-row register and ballot order are imported and explicitly verified.

This is deliberate. Set neither `ALLOW_INCOMPLETE_REFERENCE=true` nor the verification flags merely to make the worker run on election night.

## Windows: one-command setup

```bat
implement.cmd
```

Then:

```bat
run-local.cmd
```

Dashboard: `http://127.0.0.1:8000/frontend/`  
Review console: `http://127.0.0.1:8080/`

## Linux/macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev,pdf,s3,historical-ocr]'
pytest
python -m olkalou_engine.cli --root . publish --simulations 100
python -m olkalou_engine.cli --root . serve-static --port 8000
```

In a second terminal:

```bash
. .venv/bin/activate
python -m olkalou_engine.cli --root . review --port 8080
```

## Close the two reference-data gates

1. Extract the official Gazette into review CSVs:

```bash
python scripts/extract_gazette_tables.py path/to/gazette.pdf --output-dir data/review/gazette
```

2. Review and populate `scripts/streams_template.csv`, then import:

```bash
python scripts/import_streams_csv.py scripts/streams_template.csv \
  --source "IEBC Gazette Notice <number>, 5 June 2026" \
  --source-url "https://official-source.example/gazette.pdf"
```

The importer requires exactly 144 unique stream keys, non-negative registered-voter counts, verified rows and a sum of exactly 73,480.

3. Review and populate `scripts/candidates_template.csv`, then import:

```bash
python scripts/import_candidates_csv.py scripts/candidates_template.csv \
  --source "IEBC certified candidate list, Ol Kalou by-election" \
  --source-url "https://official-source.example/candidate-list.pdf"
```

The importer requires exactly nine unique candidate IDs and ballot positions 1–9.

4. Confirm the gate:

```bash
python -m olkalou_engine.cli --root . check-reference
```

It must return `"complete": true` before production ingestion.

## Run the worker

```bash
cp .env.example .env
# Set a real contact User-Agent, review token, R2/S3 credentials and alert webhook.
python -m olkalou_engine.cli --root . worker
```

A single cycle is available for controlled testing:

```bash
python -m olkalou_engine.cli --root . tick
```

## Review workflow

- Reviewer A enters all nine candidate totals plus registered, rejected, PO-valid and PO-cast controls.
- Reviewer B independently enters the same fields.
- Exact matches are run through V01–V12. Critical failures remain quarantined.
- Mismatches become `CONFLICTED` and require an adjudicator.
- Explicit adjudication can publish an internally inconsistent official form only as `DISPUTED`; the failed checks stay public.

## Object storage and redundancy

Configure R2/S3-compatible storage in `.env`. Run workers with different `WORKER_ID` values and, ideally, in different regions. Each publishes:

- `workers/<worker-id>/live.json`
- `live.json` only when its sequence exceeds the current alias

Configure both worker URLs in `frontend/config.js`; the browser accepts only the highest sequence and rejects rollback payloads.

## Form 35B reconciliation

Create a JSON object keyed by candidate ID:

```json
{"UDA": 0, "DCP": 0, "JUBILEE": 0, "PNU": 0, "PDP": 0, "KMM": 0, "FPK": 0, "PRP": 0, "NLP": 0}
```

Then run:

```bash
python -m olkalou_engine.cli --root . reconcile form35b_totals.json --output RECONCILIATION.md
```

## Repository map

```text
src/olkalou_engine/     ingestion, archive, validation, review, publication, projections
frontend/               live dashboard, previous-polls archive and methodology pages
review_console/         private keyboard-driven review UI
data/reference/         guarded live-election candidates, streams and Form 35A ROI map
data/elections/         previous-poll profiles, documents, OCR queues and verified ledgers
data/raw/               local immutable raw archive
data/public/            generated public JSON and local mirrored forms
docs/                   operations, deployment, OCR rehearsal and methodology notes
deploy/                 container and systemd deployment assets
scripts/                certified-reference import and extraction helpers
tests/                  safety-critical unit tests
```

## Deliberate limitations

- Historical OCR is always pre-fill-only. Local Tesseract helps with typed and clear scanned text, while handwriting may require cloud OCR and always requires human review.
- Live-election cloud OCR remains disabled by default. Credentials, a verified ROI/homography template and a dress-rehearsal accuracy report are required before machine-assisted use; auto-publication remains separately gated.
- The Gazette parser produces a review artifact; it never silently certifies rows.
- The watcher parser is defensive but must be tested against the exact live IEBC detail page before code freeze.
- Authentication is a bearer token, suitable behind TLS and a private access layer; it is not a full identity system.


### Windows timezone compatibility

`tzdata` is installed as a core dependency, and the worker has a fixed UTC+03:00 fallback for East Africa Time when the Windows IANA timezone database is unavailable.

## IEBC portal sync hotfix v0.4.1

The parser supports the current IEBC JavaScript constituency rows and verified constituency-scoped Download All ZIPs. It refuses redirects to the national index and rejects a ZIP unless its supported form count exactly matches the portal's reported count. See `SYNC_FAILURE_FIX_NOTES.md`.

## Hierarchical IEBC form discovery

For historical elections such as Banissa, the engine follows the portal route from county to constituency, ward, polling centre and polling stream. It downloads the individual cloud-link file shown on each leaf row and deliberately ignores higher-level `Download All` controls, which can return broader HTML selector pages instead of constituency form files. See `IEBC_HIERARCHY_FIX_NOTES.md`.

## Always-on realtime sync

For data updates without waiting for a GitHub Pages deployment, run:

```bash
python -m olkalou_engine.cli --root . realtime-api --host 0.0.0.0 --port 8090
```

The service checks Ol Kalou every 30 seconds by default, provides an authenticated **Check IEBC now** endpoint and can mirror current JSON directly to Cloudflare R2. See `docs/REALTIME_SYNC.md`.
