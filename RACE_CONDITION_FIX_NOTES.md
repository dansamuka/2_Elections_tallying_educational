# Race condition fix — sync run #9 failure

## What happened

Run #9 of "Sync IEBC forms and OCR" failed after 10m18s. The OCR/sync step
itself succeeded (9m42s, and it was doing real work — genuine extraction
JSON files for real Banissa documents, confirming the historical pipeline
is actually pulling from the live portal now). The failure was entirely in
the final "Commit only meaningful changes" step:

```
CONFLICT (add/add): Merge conflict in .../ocr/extractions/e1cf1b1a75602029-p001.json
[... six more add/add conflicts on other extraction files ...]
CONFLICT (content): Merge conflict in .../ocr/form35b_review.json
CONFLICT (content): Merge conflict in .../ocr/summary.json
CONFLICT (add/add): Merge conflict in .../sync_status.json
CONFLICT (content): Merge conflict in data/public/elections/banissa-2025.json
CONFLICT (content): Merge conflict in data/public/live.json
CONFLICT (content): Merge conflict in data/public/workers/worker-a/live.json
error: could not apply 5c1ffeb... Sync IEBC historical forms and OCR review data
```

## Root cause

The commit step ended in `git commit; git pull --rebase origin main; git
push`. Every single file that conflicted is a file some process **wholesale
regenerates from scratch on every run** — OCR extraction JSON, the OCR
summary/status files, the rebuilt public election payloads, `live.json`.
None of them are hand-edited. A rebase tries to reconcile two versions of a
file at the *content* level; for a fully-regenerated JSON blob, two
independent regenerations will essentially always differ (different
`generated_at`, different `seq`, even if the underlying facts are
identical) — so a rebase over these files doesn't fail occasionally, it
fails **by construction**, the moment `origin/main` has moved at all
between this run's checkout and its push.

`concurrency: group: historical-forms-sync, cancel-in-progress: false` was
already correctly configured in the workflow (this was not a "no
concurrency guard" bug) — that stops two runs of *this specific workflow*
overlapping. It cannot, and does not, stop `origin/main` moving for any
other reason in the ~10 minutes a real OCR pass takes: another workflow,
somebody running `PUSH_TO_GITHUB.cmd` locally, or a direct push. Looking at
`scripts/github/push_to_github.ps1`: it does `git add --all; git commit;
git push` with **no fetch or pull at all** beforehand — it can land a
commit on `main` at any moment, including mid-way through a scheduled
sync's OCR step, with no coordination between the two. That script isn't
provably the "other side" of this specific race (GitHub doesn't expose
enough in this log to say for certain), but it's a real, live way for
`main` to move underneath a running sync job regardless of the concurrency
group, and the fix needs to be correct against that possibility whether or
not it's what happened this time.

## Fix

`scripts/publish_regenerated_outputs.sh` (new) replaces the rebase
entirely. It never attempts a content-level merge:

1. Stage the paths this run produced.
2. If nothing changed, exit cleanly.
3. Otherwise, loop (up to 5 attempts): fetch `origin/main`, `git reset
   --mixed origin/main` (moves HEAD + the index to match origin exactly —
   critically, this does **not** touch the working tree, so this run's
   already-generated files sitting on disk are untouched), re-stage the
   same paths (now diffed against origin's current tip instead of this
   run's stale starting point), commit, push.

Because the new commit is always "whatever origin/main currently is, plus
this run's regenerated paths overlaid on top," there is no content to
merge and therefore nothing to conflict on. The only way this can still
fail is if `origin/main` advances faster than 5 short fetch-reset-push
cycles can keep up with — at which point it fails loudly with a
`::error::` annotation rather than silently, and the next scheduled run
simply regenerates everything fresh from current portal state. Nothing is
permanently lost in either case; a delayed run is the worst outcome.

The workflow's "Commit only meaningful changes" step now just calls this
script. `.github/workflows/ci.yml` was not changed to test it directly (a
GitHub-Actions-only integration is hard to exercise meaningfully in CI);
instead:

`tests/test_publish_regenerated_outputs.py` runs the actual script against
real, local, temporary git repositories and proves, with real git
operations (not mocked):

- two runs that independently regenerate the *same* files never conflict,
  reproducing the exact run #9 shape;
- an unrelated concurrent push (simulating `PUSH_TO_GITHUB.cmd`, or a
  person editing something else) survives untouched, not clobbered;
- a run that produces no actual changes exits cleanly (`changed=false`);
- a run with a real change exits cleanly (`changed=true`);
- a path that doesn't exist on disk at all doesn't crash the script — this
  one is a real bug the test development process itself caught: `git add`
  fails hard, not silently, on a pathspec with zero matches, which would
  have broken the very first run against a fresh checkout where e.g.
  `data/public/workers/` doesn't exist yet.

## Also fixed: `push_to_github.ps1`'s failure message

Unrelated to the automated fix, but directly relevant: if that script's own
push is ever rejected, it threw `"Git push failed. Check repository
permissions and branch protection."` — which is misleading. The overwhelmingly
likely cause on this repo is the scheduled sync workflow having pushed in
the last few minutes, not a permissions problem, and the old message would
send whoever hit it down the wrong troubleshooting path. Added a
pre-push divergence check with an accurate explanation and a concrete next
step (wait and retry, or `git pull --rebase` first).

**This PowerShell change is NOT execution-tested** — there is no `pwsh` /
PowerShell available in the environment this was built in, only a
brace/paren balance check. It's a small, additive change (a check before
the existing push, and a clearer message on the existing failure path; the
push mechanism itself is unchanged), but verify it actually runs correctly
on a real Windows machine before relying on it — don't take this one on
the same confidence as the bash fix above, which is proven against real git
operations in `tests/test_publish_regenerated_outputs.py`.

## Is `main` in a bad state right now?

No action needed there. GitHub Actions runners are ephemeral — run #9's
failed job never reached `git push` (it failed during the rebase, before
that), so nothing corrupt or half-merged was ever pushed. Whatever run
landed successfully before it is exactly what's on `main` now; run #9's own
contribution was simply never committed anywhere and is gone with the
runner. The next scheduled run (now using the fixed script) will
rediscover and correctly commit anything that was lost.

## Update — validated on a real Windows machine, one real bug found and fixed

`push_to_github.ps1` was run for real after the fix above landed. Worth
recording what that run actually showed:

**The good news first.** The script's existing "run the full test suite
before allowing a push" gate worked exactly as designed — it caught a
problem and correctly refused to push. And of the 86 tests in the suite,
**81 passed outright on Windows**, including every test written before this
session (validator, state machine, publisher, provisional aggregates,
review-console auth, archive/historical-election handling — all of it).
That's real, independent, cross-platform confirmation of everything else
this project has built, not just an assumption it would also work on
Windows.

**The 5 that failed, and why.** All 5 were the brand-new
`tests/test_publish_regenerated_outputs.py`, all with the identical error:
`FileNotFoundError: [WinError 2] The system cannot find the file specified`
trying to launch `bash`. Root cause: a bare Windows PATH does not include
`bash`, even when Git for Windows — which bundles one — is installed; only
`git.exe` is normally on PATH. The test file called `["bash", ...]`
directly and had no fallback.

Fixed in `tests/test_publish_regenerated_outputs.py`:
- `_find_bash()`: checks PATH first (works on Linux/macOS/CI/WSL
  unchanged), then derives Git for Windows' bundled bash from wherever
  `git.exe` actually resolves to (covers the common case: git on PATH,
  bash not), then a couple of hardcoded install locations as a last
  resort.
- If truly nothing is found, the whole module skips cleanly
  (`pytest.mark.skipif`, 5 skipped, not 5 failed/errored) with a message
  explaining this doesn't indicate a real problem — production always runs
  the actual script inside GitHub Actions' `ubuntu-latest`, which always
  has bash.
- A second, related bug in the same two tests: they replaced the entire
  subprocess environment with `{"GITHUB_OUTPUT": ..., "PATH": "/usr/bin:/bin"}`
  — a Unix-only path string that would have broken process creation on
  Windows even once bash was found (Windows needs several of its own
  environment variables just to launch anything). Fixed to extend the real
  environment (`os.environ.copy()` + set `GITHUB_OUTPUT`) instead of
  replacing it.

**What I could verify vs. what I couldn't.** Confirmed on Linux: the
PATH-based lookup still works (all 5 tests pass), the fallback chain
executes cleanly through every branch without crashing when bash truly
can't be found (tested by mocking `shutil.which`), and the skip mechanism
engages correctly rather than erroring (verified directly — 5 skipped, 0
failed). What I could **not** verify: whether the Git-for-Windows-relative
path derivation actually lands on a real `bash.exe` on Sir's specific
machine, since that needs a real Windows box to check. If these 5 still
don't run next time (as opposed to skipping cleanly), that's the next
thing to look at — but either outcome (running for real, or skipping
cleanly) is fine; the only bad outcome the old code had was crashing and
threatening to block the whole push over an environment-detection gap
unrelated to code correctness.

**Also added while reviewing the rest of this process:** the local gate
ran `pytest` but not `ruff check`, even though CI does
(`ruff check src tests scripts` in `ci.yml`). That meant a change could
pass every local check and still fail on GitHub over lint alone. Added the
same ruff invocation to `push_to_github.ps1` right after the pytest gate,
matching CI exactly. Same caveat as the rest of this file's PowerShell
changes: not execution-tested, no PowerShell available in this environment
— verify it runs cleanly before relying on it.

## One more thing worth deciding, not fixed here

The OCR/sync step took 9m42s against a 5-minute schedule. That's no longer
a *correctness* problem (the fix above is correct regardless of timing),
but it likely means most cron ticks are queuing behind a still-running
previous one rather than actually firing fresh, which costs Actions
minutes for not much freshness gain. Worth checking whether 9m42s was a
one-time cost (first real run against 81 Banissa documents, with nothing
cached yet — the manifest/extraction-dir caching in `historical_ocr.py`
should make most subsequent ticks much faster, since it skips
already-processed pages) or the steady state. If it stays this slow,
lengthening `cron:` in `sync-historical-forms.yml` (and the matching
`interval_minutes` in `data/elections/sync.json`) from 5 to something like
15 minutes would cut the queuing/cost without weakening anything the fix
above provides. Left as your call rather than changed here, since it's a
freshness/cost tradeoff that depends on things I can't see from here
(actual steady-state run time, how much Actions usage this account has to
spend).
