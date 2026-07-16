# Ol Kalou Sentiment & Early Alert Module

Implements `SPECIFICATION.md` (Phase 0 + Phase 1, plus the Phase 2 hook and a
lightweight slice of Phase 4) and the early-alert addendum. Drop this
`sentiment/` folder into `2_Elections_tallying_educational/` at the repo root.

## What's implemented vs. stubbed

**Working now, tested with synthetic demo data (network-restricted sandbox
means I couldn't hit the live X/GDELT endpoints from here):**
- Full pipeline: normalize → dedupe → redact → classify → sentiment → confidence → alerts → aggregate
- Public-search X collector (`collect_x_public.py`) - written against the documented recent-search endpoint
- Authenticated home-timeline collector (`collect_x_private.py`) - OAuth1 user-context, opt-in via `SENTIMENT_X_MODE`
- GDELT news collector (`collect_news_gdelt.py`)
- Manual incident notes (`collect_manual_notes.py`)
- Early-alert logic per the addendum: corroboration thresholds, severity ladder, human override hook
- Dashboard (`docs/sentiment/index.html`) with a bundled demo fallback
- GitHub Actions workflow with observation-window gating and cursor advancement
- 9 automated acceptance tests (`tests/test_acceptance.py`) - all passing

**Explicitly not built yet (matches Phases 3 and 5 in the spec, on purpose):**
- Multilingual ML sentiment model (Phase 3) - current lexicon is small and auditable by design
- Full reviewer console (Phase 4) - only the minimal `config/incident_overrides.json` hook exists
- Historical frozen-dataset research tooling (Phase 5)

## First-time setup

1. Copy `sentiment/` into your existing repo, alongside the tallying engine.
2. Add repository secret `X_BEARER_TOKEN` for public-search mode. This is
   the single highest-leverage step - nothing collects from X without it.
3. Optionally add `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`,
   `X_ACCESS_TOKEN_SECRET`, `X_USER_ID` for authenticated home-timeline mode,
   and set the repository variable `SENTIMENT_X_MODE` to `private_home` or
   `hybrid`.
4. Confirm GitHub Pages serves `docs/` (or wherever your Pages source is
   configured) so `docs/sentiment/index.html` is reachable.
5. Run the workflow once manually (`workflow_dispatch`, `override_window: true`)
   to confirm collectors run without errors before relying on the schedule.

## Local development

```bash
pip install -r requirements.txt
cd scripts
python3 build_public_json.py --demo --mode demo   # generates data/public/sentiment/latest.json from synthetic data
cd ..
python3 tests/test_acceptance.py                  # run the acceptance suite
```

Open `docs/sentiment/index.html` directly in a browser to preview the
dashboard - it'll fail the relative fetch (no local server) and fall back to
the bundled `DEMO_FALLBACK` automatically, which is the same fallback path
used in production if a live payload is ever missing.

## Election-day checklist

- [ ] `X_BEARER_TOKEN` secret set
- [ ] Manual `workflow_dispatch` test run completed successfully
- [ ] `config/incident_overrides.json` and `config/manual_notes.json` are both
      reset to empty before election day, and you know who (if anyone besides
      you) is allowed to edit them during the live window
- [ ] Dashboard reachable at its GitHub Pages URL
- [ ] Decide now: do you want the optional private webhook notification for
      alerts (not built here - addendum Section D), or is the public panel
      plus manual override enough for this election?

## Traceability & evidence trail

Every run produces a private audit record (`data/private/sentiment/audit/*.json`)
with the fields deliberately excluded from the public payload restored: raw
post/article text, the real (unhashed) author reference, platform ID, and -
critically - which alert (if any) each item contributed to via
`contributed_to_alert`. That's what you pull up if an alert ever needs to be
traced back to the specific posts behind it.

**This never touches the public repo or its Actions artifacts.** On a public
GitHub repo, anyone signed in can view and download Actions artifacts and logs
from workflow runs - so instead, the workflow pushes each run's audit file to
a **separate, genuinely private repo** you control.

**One-time setup:**
1. Create a new **private** GitHub repo, e.g. `dansamuka/ol-kalou-evidence-private`
2. Generate a fine-grained PAT scoped to *only that repo*, `Contents: Read and write`
3. In `2_Elections_tallying_educational`'s repo settings:
   - Add secret `EVIDENCE_REPO_TOKEN` = that token
   - Add repo variable `EVIDENCE_REPO` = `dansamuka/ol-kalou-evidence-private`

That's it - the workflow's "Push evidence trail" step is a no-op until both
of those are set (safe default: without them, raw data for each run is simply
discarded after processing, same as before this feature existed).

**Finding the evidence behind a specific alert:**
1. Note the alert's `id` (e.g. `ol-kalou-2026:security`) and roughly when it appeared
2. In the private evidence repo, open `runs/`, find the audit file closest to that time
3. Filter its `items` array for `"contributed_to_alert": "ol-kalou-2026:security"` -
   that's your list of raw posts, with real timestamps and (unhashed) author
   references, that fed that alert

**Retention is a policy decision, not a code default** - the pipeline doesn't
delete anything from the evidence repo itself. Decide up front: who else (if
anyone) gets access to that private repo, and when you'll purge it (e.g. 30
days after results are certified). Treat it like any sensitive access log -
restrict collaborators, don't make it public, and don't keep it longer than
you need it for.

## Known simplifications worth knowing about

- **One alert per (election, category) per run**, not per discrete incident.
  Two unrelated security incidents on the same day will show as a single
  merged alert. Per-incident clustering is real Phase 4 work.
- **Headline-only news sentiment.** The GDELT collector currently only
  captures the headline, so "headline sentiment separate from article-body
  sentiment" (spec Section 4.5) isn't meaningfully separated yet - both
  fields would show the same score. Pulling full article text (via the
  optional RSS path in Section 1.3) is the natural next step.
- **The unique-source metric is a per-run, not cross-run, estimate** - by
  design (Section 7.6) - so don't read `unique_source_estimate` in the
  summary as a running total of distinct people all election day.
