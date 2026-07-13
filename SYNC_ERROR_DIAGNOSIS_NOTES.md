# Sync error diagnosis — live.json vs. archive.html divergence

## What was actually wrong

Not stale data — an incomplete deployment. The repo contains two complete,
independently-working pipelines that never talk to each other:

**Pipeline A** — `worker` → `EngineDB` (`data/state/engine.sqlite3`) →
`review` console → `publish` → `data/public/live.json` (schema
`olkalou.live.v2`). This is the ONLY thing `frontend/index.html` ("Ol Kalou
Tallying Wall") reads — `frontend/config.js` hardcodes `liveUrls: ["../data/
public/live.json"]`, and `frontend/app.js:25` hard-rejects any other schema.

**Pipeline B** — `archive-sync` → `historical_sync.py`/`archive.py` →
`data/elections/<id>/` → `archive-build` → `data/public/elections/<id>.json`
+ `catalog.json` (schema `kenya.election.archive.v1`). This is what
`frontend/archive.html`/`archive.js` reads.

Both use the same corrected reference data (`data/reference/streams.json`:
Rurii 33 / Kanjuiri Range 32 / Karau 27 / Kaimbaga 27 / Mirangine 25 = 144,
register 73,480) and the same fixed hierarchy crawler (`portal.py` — both
`worker.py` and `historical_sync.py` import it directly). They agree on the
facts. They just publish to different files, and only Pipeline B is
scheduled.

`.github/workflows/sync-historical-forms.yml` runs every 5 minutes
(`cron: "2/5 * * * *"`, line 5) but only ever calls `archive-sync` (line 118,
pre-fix). It never calls `publish`, so `data/public/live.json` was frozen at
16:02 (one manual local run) while `archive.html`'s data kept updating
through 19:23. Even a manual `publish` run wouldn't have helped: the commit
step (`git add data/elections data/public/elections`, line 158 pre-fix)
never staged `data/public/live.json`, so it could never reach Git or the
deployed Pages site.

Confirmed live: `python -m olkalou_engine.cli --root . publish` ran cleanly
on the first try against current reference data (73,480 registered, 144
streams, exit 0) — Pipeline A's code is not broken, it's just never invoked
or committed.

## The deeper point

`deploy/systemd/olkalou-worker@.service` is a template for a real,
continuously-running host (`/opt/olkalou-live-engine`, dedicated `olkalou`
user) — matching the original spec's "Option A: one always-on worker"
recommendation. There's no evidence in this export that it has actually been
provisioned anywhere. `data/public/live.json`'s single 16:02 snapshot is
consistent with one local test run, not a deployment.

`sync-historical-forms.yml` was always meant as the fallback/historical path
(spec section 4.1, "Option C") — it has become, by default, the *only* thing
keeping any page current, because it's the only piece that runs without
needing a server to be provisioned.

## Fix applied now (low-risk)

In `.github/workflows/sync-historical-forms.yml`:

1. Added a "Republish live.json (Tallying Wall)" step immediately after the
   `archive-sync` step, running `python -m olkalou_engine.cli --root .
   publish`. This is a lightweight, no-network rebuild from already-current
   `data/reference/*.json` + `EngineDB`, safe to run every 5-minute tick.
2. Changed the commit step's `git add` to include `data/public/live.json`
   and `data/public/workers`, so the republished file actually reaches Git
   and the deployed site.

This makes `index.html` auto-refresh again, on the same 5-minute cadence as
`archive.html`, with no frontend changes and no new dependency.

## What this fix does NOT do — decide before Thursday

1. **It does not make Pipeline A fast.** GitHub Actions scheduled runs are
   routinely delayed under load — this was the whole reason the original
   spec called a 5-minute Actions cron a fallback, not the primary mechanism,
   for election night. If you want `index.html` to update within seconds of
   a form landing (not "within 5 minutes, GitHub load permitting"), deploy
   `deploy/systemd/olkalou-worker@.service` to a real always-on host — this
   is genuinely the correct fix, this patch is a stopgap.
2. **Only `worker-a` exists.** `data/public/workers/` has no `worker-b/` —
   the dual-worker redundancy the systemd unit is templated for
   (`olkalou-worker@a`, `olkalou-worker@b`) has never actually been stood up
   twice. Single point of failure right now.
3. **Pipeline A and B still don't share review state.** `archive-sync`'s OCR
   review queue (`data/elections/ol-kalou-2026/ocr/review_queue.csv`, once
   forms start arriving) is separate from `EngineDB`'s review queue (the
   interactive `review_console/`). A human reviewing forms in one queue does
   not verify anything in the other. Decide which review workflow reviewers
   will actually use Thursday night, and make sure `publish`'s figures come
   from that same queue -- otherwise `live.json` will keep reporting 0
   published even as real forms get reviewed elsewhere.

## Validation

- `.github/workflows/sync-historical-forms.yml` parses as valid YAML after
  the edit.
- `python -m olkalou_engine.cli --root . publish` exits 0 and produces a
  correct payload against current reference data (verified manually, outside
  CI, in an isolated venv against this exact export).
