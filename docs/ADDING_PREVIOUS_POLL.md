# Add a previous poll

The historical module discovers election profiles under `data/elections/<election-id>/`. The website selector is generated from those folders, so a new contest does not require changes to `archive.html` or `archive.js`.

## 1. Create the folder

```text
data/elections/example-2024/
  election.json
  streams.json
  results_template.csv
  documents/
```

Use a lowercase, URL-safe ID such as `banissa-2025`.

## 2. Define `election.json`

Required sections:

- `id` and `mode: "ARCHIVE"`;
- election title, date, county and constituency codes;
- configured IEBC forms-portal index and expected Form 35A count;
- certified register source and total;
- candidate IDs, names, parties and accessible colours;
- official declaration, with separate source notes for every total;
- optional bloc definitions and methodology note.

An official declared total must never be labelled a sum of Form 35As until all source forms have been independently transcribed and reconciled.

## 3. Build `streams.json`

Every row needs:

```json
{
  "stream_key": "040-009040001101801-01",
  "polling_station_code": "009040001101801",
  "station_name": "SAMPLE PRIMARY SCHOOL",
  "stream_no": 1,
  "ward_code": "0196",
  "ward_name": "BANISSA",
  "registered": 432
}
```

The loader rejects duplicate keys, duplicate polling-station codes, the wrong number of streams, or a register sum that differs from `election.json`.

## 4. Add and OCR source documents

Place all available Form 35A, Form 35B, Gazette and supporting election PDFs/images under `documents/`. Then run:

```bash
python -m olkalou_engine.cli --root . archive-ocr example-2024 --engine auto
```

This creates `ocr/review_queue.csv`. It is a pre-fill only; OCR never updates the verified ledger. See `docs/HISTORICAL_OCR.md`.

## 5. Generate and review the transcription CSV

Copy the Banissa CSV header and create one row per stream. Candidate columns must use the candidate IDs from `election.json`. Each completed row contains:

- genuine `reported_at` timestamp;
- archived/source `form_url`;
- independent verification state;
- candidate votes;
- registered-on-form, rejected, PO-valid and PO-cast controls;
- reviewer identities and notes.

The importer rejects rows failing V01, V02, V03 or V07.

## 6. Run the pipeline

```bash
python -m olkalou_engine.cli --root . archive-run example-2024
python -m olkalou_engine.cli --root . archive-import example-2024 \
  data/elections/example-2024/results_template.csv
python -m olkalou_engine.cli --root . archive-build example-2024
python -m olkalou_engine.cli --root . archive-list
```

`archive-run` performs portal discovery and immutable downloads. `archive-import` creates the verified stream ledger. `archive-build` regenerates the public election payload. `archive-list` rebuilds the website catalog.

## 7. Publish

Double-click `PUSH_TO_GITHUB.cmd`. The Pages workflow publishes every file under `data/public`, including the new election payload and archived forms.

## Replay rule

Replay is enabled only when:

1. every expected stream has a verified result; and
2. every result has a genuine reporting timestamp.

Missing data keeps the replay visibly **WITHHELD**. The module never fabricates station sequence or timing.

## Optional portal-bootstrap benchmark mode

For a past contest whose source forms are available but whose certified atomic register is not yet loaded, use the narrowly-scoped benchmark pattern demonstrated by `malava-2025`:

- set `portal.bootstrap_streams_from_portal: true`;
- set `register.verified: false`;
- set `ocr.benchmark_only: true`;
- set `ocr.candidate_list_complete: false` where the legal roster is incomplete; and
- start `streams.json` with an empty `streams` array and `bootstrap_from_portal: true`.

The first sync writes a review-only stream skeleton only when the portal returns exactly the configured expected number of individual Form 35As. Registered values and wards remain unresolved. Benchmark rows may be human-confirmed for OCR accuracy, but they cannot pass verified import or publish a tally.
