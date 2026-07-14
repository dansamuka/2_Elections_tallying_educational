# Realtime sync implementation · 14 July 2026

Implemented an election-specific, always-running sync path that removes GitHub Actions and GitHub Pages deployment from the critical data-refresh loop.

Key additions:

- `olkalou_engine.realtime`: authenticated trigger API, public status/data endpoints, deduplicated jobs and a 30-second scheduler.
- `olkalou_engine.public_mirror`: atomic local JSON plus direct R2/S3-compatible publishing.
- Per-stage progress from portal discovery through OCR, payload build and mirror publication.
- Frontend multi-origin fetch using the highest sequence number.
- Owner-only **Check IEBC now** and two-second job-status watching.
- Five-second public refresh and fallback to GitHub Pages.
- Docker, systemd, Windows launch/configuration scripts and an optional Cloudflare Worker edge gateway.
- GitHub Actions retained only as a slower backup, with scheduled runs isolated to Ol Kalou.

Validation in this package: 118 Python tests and four browser execution suites, including a realtime trigger/watch test.
