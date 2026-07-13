# Election-night runbook

## T-24 hours

- `pytest` and `python -m compileall -q src` pass.
- `check-reference` returns complete with no errors.
- Confirm all 144 grid cells have real official stream keys and registered totals.
- Review candidate legal names and row order against the certified form/list.
- Confirm `PUBLIC_BASE_URL`, R2/S3 bucket, CORS and immutable raw-object policy.
- Test alerting by stopping a worker and by injecting a parser fixture with no Ol Kalou row.
- Test two independent review accounts and one adjudicator account.
- Replay the rehearsal corpus end-to-end and archive the accuracy report.

## Code freeze — 12:00 EAT, 16 July 2026

No feature changes after freeze. Configuration and emergency parser selectors only. Tag the release and save the exact deployed commit hash in the methodology page.

## 17:00–20:00

- Set status to `COUNTING` after polls close.
- Zero forms is expected; do not weaken the canary before 19:00.
- Confirm both workers heartbeat and the dashboard shows fresh zero coverage.

## Form-arrival window

1. Watch archive growth before OCR/review throughput.
2. Keep the queue under ten forms; call relief if it exceeds ten.
3. Never use one reviewer twice for the same stream/version.
4. Treat every amended form as a new version.
5. Critical check failures remain quarantined; do not “fix” the official form arithmetic.
6. Use adjudication only after opening the source image. A critical official inconsistency publishes as `DISPUTED`, not clean.
7. If the feed is stale, preserve the last-known-good payload and investigate the worker/portal; never zero the dashboard.

## Incident actions

| Trigger | Immediate action |
|---|---|
| Portal non-200 ×3 | Verify portal manually; fail over; preserve existing archive and LKG. |
| Parser discovers zero after 19:00 ×3 | Compare live HTML with saved fixture; update selector only if structure changed. |
| Worker heartbeat >3 min | Promote worker B; inspect logs after continuity is restored. |
| Queue >10 | Add relief reviewer; do not enable unsafe auto-publication. |
| Sequence stops advancing with pending forms | Check object-store write permissions and publisher logs. |
| Wrong public number | Quarantine affected version, ingest corrected/new source version, append correction; never rewrite history. |

## Post-declaration

- Archive Form 35B as an immutable new source object.
- Independently key 35B totals twice.
- Generate `RECONCILIATION.md`.
- Confirm candidate deltas, all anomalies, corrections and 144 source links.
- Freeze the archive and publish checksums.
