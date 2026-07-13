# Deployment

## Recommended topology

- Static dashboard: GitHub Pages or any static CDN.
- Public objects: Cloudflare R2/S3-compatible bucket with CORS `GET, HEAD`, public read and `Cache-Control: max-age=20` for JSON.
- Raw forms: same bucket, immutable names and one-year immutable cache.
- Worker A and B: separate regions/providers, distinct `WORKER_ID`, same object bucket.
- Review API: private HTTPS endpoint behind an access proxy/VPN; do not expose a default token.

## Container

```bash
docker build -t olkalou-live-engine .
docker compose up dashboard review
# Once certified reference data is loaded:
docker compose up worker-a
```

Deploy worker B from a second host with `WORKER_ID=worker-b`.

## systemd

Copy the repository to `/opt/olkalou-live-engine`, install the virtual environment, place a protected environment file at `/etc/olkalou/engine.env`, then:

```bash
sudo cp deploy/systemd/olkalou-worker@.service /etc/systemd/system/
sudo cp deploy/systemd/olkalou-review.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now olkalou-worker@worker-a
sudo systemctl enable --now olkalou-review
```

Use a second machine for `worker-b`; two services on one machine are not meaningful redundancy.

## Security minimum

- Replace `REVIEW_API_TOKEN=change-me` with a long random secret.
- Put review traffic behind TLS and restricted access.
- Give worker credentials only `GetObject/PutObject` rights for its prefix.
- Keep bucket listing disabled even when individual public objects are readable.
- Rotate leaked credentials; do not commit `.env`.
- Preserve raw source bytes and metadata; never edit an archived object in place.
