# Realtime / sub-10-minute sync

## What changed

The frontend no longer needs to wait for a GitHub Actions runner, a Git commit, a Pages artifact and a Pages deployment before it can see a new JSON payload.

The new `realtime-api` service is a long-lived FastAPI process that:

1. checks only the selected election;
2. reuses its installed Tesseract/OpenCV/Python environment;
3. downloads and OCRs only new or stale source hashes;
4. writes election JSON atomically;
5. mirrors `live.json`, election JSON, the catalog and job status directly to Cloudflare R2/S3-compatible storage; and
6. exposes progress to the browser every two seconds while a manually triggered job is running.

GitHub Actions remains a backup reconciliation path. Scheduled Actions now target Ol Kalou only; Malava and Banissa cannot delay the live-election fallback job.

## Browser behaviour

- **Refresh data** immediately requests the newest payload from R2/API and GitHub Pages in parallel, then uses the highest `seq`.
- **Check IEBC now** asks the owner for a token, starts an election-specific job and follows its status until completion.
- The token is held only in `sessionStorage`; it is not written into `config.js`, local storage or the repository.
- Once a valid token has been entered, subsequent **Refresh data** clicks can also start a deduplicated check.
- Repeated clicks return the existing job rather than starting overlapping OCR work.

## Start locally with Docker

```bash
copy .env.example .env
# Edit .env: set REALTIME_API_TOKEN and, for R2, S3_* values.
docker compose up -d realtime dashboard
```

Endpoints:

- dashboard: `http://localhost:8000/frontend/`
- realtime API: `http://localhost:8090/api/health`

Configure the static frontend:

```bash
python scripts/configure_realtime_frontend.py \
  --api-base https://sync.example.org \
  --data-base https://data.example.org/ol-kalou
```

## R2 values

Cloudflare R2 uses the existing S3-compatible settings:

```dotenv
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=olkalou-election-data
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PUBLIC_BASE_URL=https://data.example.org
S3_PREFIX=ol-kalou
```

The service writes:

```text
ol-kalou/live.json
ol-kalou/elections/catalog.json
ol-kalou/elections/ol-kalou-2026.json
ol-kalou/realtime/status/ol-kalou-2026.json
```

Use a public custom domain for read-only JSON. Keep R2 write credentials only on the Python service.

## Production layout

```text
IEBC portal
    ↓ 30-second scheduler / owner trigger
Long-lived Python realtime service
    ↓ atomic JSON + immutable form archive
Cloudflare R2
    ↓ 5-second browser polling
GitHub Pages frontend
```

The optional Worker in `deploy/cloudflare-worker/` serves R2 JSON and safely proxies the owner trigger to a private origin token.

## Security controls

- The service refuses to start with `REALTIME_API_TOKEN=change-me`.
- Trigger routes require `Authorization: Bearer ...`.
- Public routes are read-only.
- CORS is restricted through `REALTIME_CORS_ORIGINS`.
- Human-confirmed tally rules are unchanged; rapid OCR does not auto-publish votes.
- `AUTO_PUBLISH_MACHINE_VERIFIED` remains false.

## Expected timing

- already-published JSON refresh: generally under one second;
- portal check with no change: commonly 10–30 seconds;
- one to five new forms through incremental OCR: commonly one to three minutes;
- first Malava 198-form bootstrap: intentionally outside the live path and may exceed ten minutes.

These are operational targets, not guarantees: IEBC response time, network availability and OCR engine latency remain external dependencies.
