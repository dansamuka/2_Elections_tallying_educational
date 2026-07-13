# 13 Jul 2026 audit and corrections

Full pass requested after the sync-error diagnosis (see
`SYNC_ERROR_DIAGNOSIS_NOTES.md` for that fix specifically). This covers
everything else found while auditing the whole repo: tests, lint, data
provenance, and a real security bug.

## Baseline, before any fixes

- 57 pytest tests passed, ruff clean, `python -m compileall` clean,
  `frontend/app.js` / `archive.js` / `config.js` passed `node --check`.
- `python -m olkalou_engine.cli --root . publish` ran cleanly against
  current reference data (confirms Pipeline A's code is sound; it was a
  scheduling/commit gap, not a code defect -- see the sync-error notes).

None of that was wrong. The gaps below are things that automated checks
don't catch on their own: a security default, a data-provenance claim that
didn't match reality, and a couple of unverified-vs-verified inconsistencies.

## 1. Security: review console auth-bypass (fixed)

`src/olkalou_engine/review_api.py`, `require_token()`: whenever
`REVIEW_API_TOKEN` was left at its shipped default `"change-me"`
(`.env.example`, `config.py:44`), the function returned immediately with
**no check at all** -- not "the password is 'change-me'", but "there is no
password". Combined with `REVIEW_HOST` defaulting to `0.0.0.0` (all network
interfaces, not just localhost) and CORS `allow_origins=["*"]`, an operator
who deployed the review console without explicitly setting a real token
would unknowingly run it wide open on the network -- and this console can
publish election results.

There was also a module-level `app = create_app()` at the bottom of the
same file, unused by every real entrypoint (docker-compose's `review`
service, `deploy/systemd/olkalou-worker@.service`, and `cli.py`'s `review`
subcommand all call `create_app(settings)` explicitly with real settings).
It meant merely *importing* the module executed side-effecting
initialization using whatever default env happened to be present.

**Fix:** `create_app()` now refuses to start (`RuntimeError`) if the token
is still `"change-me"`, and `require_token()` no longer has a bypass branch
-- once the app starts, the configured token is always checked. Removed the
unused module-level `app = create_app()`. Confirmed `review_console/index.html`
already sends `Authorization: Bearer <token>` on every call (it was built
correctly; only the backend had the bypass), so no frontend changes needed.

Added `tests/test_review_api_auth.py` (6 tests): refuses default token,
starts with a real one, health check stays open, protected endpoints reject
missing/wrong tokens and accept the correct one. All pass.

**Before you deploy:** set `REVIEW_API_TOKEN` to something real in your
actual `.env`. The console will now refuse to start otherwise -- that's
intentional.

## 2. Data provenance: register total and ward verification (fixed)

`data/reference/streams.json` cited an unopened PDF
(`OsfnFvMWui.pdf`) for the 73,480 register total and marked
`register_source_verified: false` -- correctly cautious. But every entry in
`ward_summary` was separately marked `ward_total_verified: true`, which
doesn't hold together: you can't have verified the ward breakdown of a
total you haven't verified the source of.

Checked independently via web search: Ol Kalou Returning Officer **Anthony
Njiraini** is on-record with Daily Nation stating 73,480 voters are
eligible to cast ballots in the 16 July 2026 by-election ("Shared
childhoods and old rivals," ~10 Jul 2026) -- a named official, on record,
independently reported. A second Nation piece separately references "the
area's 73,000 registered voters," consistent with 73,480 rounded.

**Fix:** register TOTAL now cites the RO's on-record statement as
independent verification. `ward_total_verified` corrected from `true` to
`false` on all 5 wards in both `data/reference/streams.json` and
`data/elections/ol-kalou-2026/streams.json` (they were duplicated,
identical files) -- the ward-level breakdown and all 144 individual atomic
stream rows are still genuinely unverified and remain gated. Applied via
`scripts/apply_audit_fixes_13jul.py` (kept in the repo, documents exactly
what changed and why; safe to read, not safe to re-run blindly a second
time without reviewing the diff).

Confirmed this does NOT weaken the safety gate:
`candidates.source_verified`, `candidates.ballot_order_verified`, and
`streams.register_source_verified` were left `false` throughout (press
corroboration of a total is not the same thing as opening the certified
Gazette document). `check-reference` still correctly exits 1 with the same
class of errors as before.

## 3. Data provenance: candidate list citation (fixed)

`data/reference/candidates.json`'s `source_url` pointed at the *same* PDF as
the polling-station register -- implausible, since a candidate list and a
voter register are normally different Gazette instruments. Removed the
misleading URL. Added a genuine corroborating citation: the 9-candidate
roster (names, parties, bloc assignment) is consistently reported across
seven independent Kenyan outlets (Nation, KBC Digital, The Standard,
Kahawatungu, Kenyans.co.ke, People Daily, AVDelta News). This corroborates
the roster; it does not verify ballot order or exact legal-name spelling
against the certified list, which the existing (correct) notes already flag
as still required.

## 4. Checklist item actually verified: candidate colour contrast

`docs/REFERENCE_DATA_CHECKLIST.md` had an unchecked box for "every colour
has >=3:1 contrast on `#0E1116`." Computed WCAG relative-luminance contrast
for all 9 candidate colours in `data/reference/candidates.json`: lowest is
Wilson Kigwa's `#E85D5D` at 5.54:1. All 9 clear both the 3:1 and 4.5:1
thresholds. Checked the box, recorded the numbers. Re-run this check if any
candidate's assigned colour ever changes.

## 5. CI: publish path had no regression coverage (fixed)

Root cause of the sync error (full detail in `SYNC_ERROR_DIAGNOSIS_NOTES.md`)
was that `publish` -- which works correctly -- was never invoked by
anything running on a schedule, so nothing caught `data/public/live.json`
going stale for hours. `.github/workflows/ci.yml` tested the Banissa archive
pipeline end-to-end but never touched `publish` at all. Added a
`python -m olkalou_engine.cli --root . publish` step to CI so this class of
regression fails loudly on the next push instead of silently, again.

## Checked and found genuinely fine (no fix needed)

- Banissa's `data/elections/banissa-2025/election.json` provenance: cites
  specific, distinct Gazette Notice numbers for the register (No. 15731)
  and the winner's declaration (No. 17611), and explicitly caveats the
  runner-up figure as press-reported pending Form 35B reconciliation. This
  is the standard the Ol Kalou file above now more closely matches.
- `.env.example` vs `config.py`: every environment variable has a matching
  `Field(alias=...)` and vice versa. No drift.
- `review_console/index.html`'s embedded script, and `archive.html`'s
  embedded scripts: pass `node --check`.
- `docker-compose.yml` / `Dockerfile` / `deploy/systemd/*`: paths and
  commands match the actual CLI subcommands; `review` and `worker-a`
  services correctly load `env_file: [.env]`.

## Validation after all fixes

- 63 pytest tests passed (57 original + 6 new auth tests).
- Ruff clean.
- `python -m compileall` clean.
- `check-reference` still correctly reports incomplete and exits 1 -- the
  safety gate was not weakened by any of the above.
- `python -m olkalou_engine.cli --root . publish` re-run once more against
  the fully-corrected reference data as the final step before packaging;
  `data/public/live.json` and its `workers/worker-a/` mirror both reflect
  the corrected state.
