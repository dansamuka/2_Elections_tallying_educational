# Optional Cloudflare edge gateway

This Worker gives the static GitHub Pages frontend one HTTPS origin for:

- current `live.json` and historical election JSON stored in R2;
- public per-election sync status; and
- an owner-authenticated proxy to the always-running Python sync service.

The public browser token is never hard-coded. The owner enters `OWNER_TOKEN` into the browser session. The Worker replaces it with the separate `ORIGIN_TOKEN` before calling the Python service.

```bash
cd deploy/cloudflare-worker
cp wrangler.toml.example wrangler.toml
npm install -g wrangler
wrangler secret put OWNER_TOKEN
wrangler secret put ORIGIN_TOKEN
wrangler deploy
```

Set `frontend/config.js` `realtimeApiBase` to the deployed Worker URL. Set `archiveDataBaseUrls` and `liveDataBaseUrls` to the public R2/custom-domain prefix when direct object reads are also desired.

When the frontend reads the R2 custom domain directly, apply the read-only bucket CORS policy in `r2-cors.json`. The Worker path already adds CORS headers itself.
