# Implementation status

## Delivered

| Area | Status | Notes |
|---|---|---|
| One-click GitHub package | Implemented | `PUSH_TO_GITHUB.cmd` validates, commits, creates/reconnects the repo, pushes `main`, and enables Pages. |
| GitHub Pages artifact | Implemented | Publishes the full frontend and all generated public datasets, including historical profiles and archived forms. |
| Historical election engine | Implemented | Generic profile loader, certified-register checks, portal discovery/archive, verified CSV import, public catalog, and replay events. |
| Banissa 2025 profile | Implemented | 81 certified streams, 32,703 registered voters, two candidates, official declaration provenance, and website payload. |
| Historical safety gate | Implemented | Declared totals are separated from Form 35A sums; replay is withheld until every stream and timestamp is independently verified. |
| Historical website | Implemented | Election selector, result view, 81-cell source grid, archive readiness, source ledger, provenance and replay controls. |
| Trust-first live architecture | Implemented | Archive → extraction boundary → validation → double-entry review → publication. |
| Immutable archive | Implemented | SHA-256, versioned object names, immutable caching, local and R2/S3-compatible stores. |
| Watcher | Implemented | Conditional GET, exponential backoff, manifest, structure assertion and after-19:00 canary. |
| Form amendments | Implemented | New version, V08 conflict, field-level public correction entries. |
| Validation V01–V12 | Implemented | V05 thresholds are configurable but still require dress-rehearsal calibration. |
| Publication gate | Implemented | Incomplete reference blocks worker; human matches still pass statutory validation. |
| Review console | Implemented | Independent double entry, keyboard operation, scan pane and explicit adjudication. |
| Public API contract | Implemented | `olkalou.live.v2` plus `kenya.election.archive.v1` and catalog metadata. |
| Dashboard | Implemented | Result bar, coverage, Stream Grid, projections, bloc arithmetic, tables, anomalies and corrections. |
| Staleness/LKG/rollback | Implemented | 3/10-minute banners, browser cache and monotonic sequence rejection. |
| T1/T2/T3 analytics | Implemented | Hard bound, turnout-capped bound and ward-stratified simulation. |
| Form 35B reconciliation | Implemented | CLI and Markdown generator. |
| Historical OCR ingestion | Implemented | Recursively inventories PDF/images, SHA-256 deduplicates, mirrors originals, processes every page, classifies 35A/35B, matches streams and creates a review CSV. |
| Historical OCR safety gate | Implemented | OCR never writes verified results or public candidate totals; two-person review plus V01/V02/V03/V07 import remains mandatory. |
| Same-repository updater | Implemented | One-click publisher defaults to `dansamuka/2_Elections_tallying_educational`, fetches `origin/main`, replaces changed files and does not create a new repo when it already exists. |
| Deployment assets | Implemented | Docker, Compose, systemd, CI and GitHub Pages workflow. |

## Historical-data posture

Banissa is usable immediately as an official constituency-level archive and complete polling-stream reference frame. It is not mislabelled as a Form 35A-certified replay: the replay remains off until the 81 source forms, stream figures and authentic report times are present. Running `archive-run banissa-2025` on an internet-connected machine performs portal discovery and immutable download; `archive-import` accepts the reviewed transcriptions only when V01, V02, V03 and V07 all pass.

## Live Ol Kalou production blockers intentionally not fabricated

1. **Certified 144-row polling-unit register.** Ward totals and the constituency total are staged, but each atomic row remains unresolved until imported from the official Gazette/register.
2. **Certified candidate legal names and ballot/Form 35A order.** Provisional names are visible for pre-poll design work; the production gate remains closed.
3. **Exact live IEBC result-detail HTML fixture.** Run a controlled parser rehearsal against the live portal and preserve a fixture before code freeze.
4. **OCR certification.** Google Vision/Textract adapters and template rectification are implemented, but the exact nine-row ROI map and measured accuracy on a real by-election corpus are still required. Until then, use human entry.
5. **V05 calibration.** Replace the provisional rejected-ballot band with an empirical band from the rehearsal corpus.
6. **Operational credentials and people.** R2/S3, alert webhook, TLS/private review access, two reviewers plus relief, and two independent worker deployments.

## Current live-reference correction

The code uses 73,480 as the 2026 Ol Kalou register total and explicitly warns against using the 2022 total of 72,997. It treats 144 as the expected atomic denominator but does not assume that the old 142-station explanation remains valid.

## Windows Python 3.13 hotfix — 13 July 2026

- Added `tzdata` as a core dependency.
- Added a fixed UTC+03:00 East Africa Time fallback when Windows cannot load `Africa/Nairobi`.
- Added regression tests for normal and deliberately missing timezone databases.
- Added a one-click preflight assertion before payload generation.
