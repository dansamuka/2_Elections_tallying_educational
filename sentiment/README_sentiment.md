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
- Dashboard (`frontend/sentiment.html`, linked from the existing nav) with a bundled demo fallback
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
4. Nothing extra needed for Pages - `frontend/sentiment.html` and
   `data/public/sentiment/latest.json` both sit inside the paths your existing
   `.github/workflows/pages.yml` already copies into `_site/`, so it's live as
   soon as it's on `main`.
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

## Integration note (found while wiring this into the real repo)

The spec's architecture diagram assumed a `docs/`-based Pages source, but this
repo's actual `.github/workflows/pages.yml` builds `_site/` from `frontend/` +
`data/public/` only. So: the dashboard lives at `frontend/sentiment.html` (flat,
matching `archive.html`/`methodology.html`), and `build_public_json.py` writes
to the repo-root `data/public/sentiment/latest.json` - NOT a module-local
`sentiment/data/public/`, which the real deploy pipeline never sees. The
dashboard's fetch tries `./data/public/...` then `../data/public/...` in
sequence so it resolves correctly in both the deployed `_site/` layout and a
local dev checkout, without needing to touch the existing `pages.yml` sed
rewrite step.

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
