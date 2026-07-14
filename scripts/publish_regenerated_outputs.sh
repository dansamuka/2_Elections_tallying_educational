#!/usr/bin/env bash
# Publishes regenerated output files (never hand-edited -- OCR extractions,
# rebuilt public JSON, sync-status files) without ever attempting a
# content-level merge or rebase against them.
#
# WHY THIS EXISTS: run #9 of "Sync IEBC forms and OCR" failed with
# add/add and content conflicts across ocr/extractions/*.json,
# ocr/summary.json, sync_status.json, data/public/elections/*.json, and
# data/public/live.json -- every one of them a file some process wholesale
# REGENERATES from scratch on every run, never hand-edits. `git pull
# --rebase origin main` tries to diff-merge two independently-regenerated
# snapshots of the same file at the content level, which is meaningless for
# machine output (different `generated_at`/`seq` fields alone guarantee a
# conflict) and fails hard exactly like it did there. See
# SYNC_ERROR_DIAGNOSIS_NOTES.md and RACE_CONDITION_FIX_NOTES.md for the
# full incident.
#
# The concurrency: group in sync-historical-forms.yml already prevents two
# runs of THAT workflow from overlapping -- but it does not, and cannot,
# protect against something else pushing to `main` in the ~10 minutes a
# real OCR run takes: a manual `PUSH_TO_GITHUB.cmd` run, a different
# workflow, or a person pushing directly. This script assumes that CAN
# happen and stays correct anyway.
#
# STRATEGY: never rebase, never merge. Stage what this run produced, then
# repeatedly: fetch origin, move local history to match it exactly
# (git reset --mixed, which touches only HEAD + the index -- never the
# working tree, so the files this run already generated on disk are
# untouched), re-stage those same paths, commit, and try to push. Since a
# fresh commit "origin's tree + our regenerated paths overlaid on top" can
# never produce a conflict marker, this only fails if push races itself
# more times than the retry budget allows (astronomically unlikely) --
# and even then it fails loudly rather than silently losing anything: the
# files this run produced are simply not committed, and the next scheduled
# run regenerates them fresh from current portal state.
#
# Usage: publish_regenerated_outputs.sh <path> [<path> ...]
# Requires: run inside a git work tree with an `origin` remote and `main`
# checked out. Honors GITHUB_OUTPUT (writes changed=true|false) if set;
# safe to run standalone (e.g. under test) when it is not.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <path> [<path> ...]" >&2
  exit 64
fi

emit_output() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "$1" >>"$GITHUB_OUTPUT"
  fi
}

# `git add` fails hard (not a no-op) on a pathspec that doesn't exist on
# disk at all -- a real case here, e.g. data/public/workers/ not existing
# yet on an early or first-ever run. Filter to what's actually present each
# time this is called (paths can appear between the pre-reset add and the
# post-reset add, e.g. this run creates a directory that didn't exist
# before), rather than failing the whole publish over a directory nobody
# has written to yet.
add_existing() {
  local existing=()
  for p in "$@"; do
    [[ -e "$p" ]] && existing+=("$p")
  done
  if [[ ${#existing[@]} -gt 0 ]]; then
    git add -- "${existing[@]}"
  fi
}

PATHS=("$@")

git config user.name "github-actions[bot]" 2>/dev/null || true
git config user.email "41898282+github-actions[bot]@users.noreply.github.com" 2>/dev/null || true

add_existing "${PATHS[@]}"
if git diff --cached --quiet; then
  echo "No new or changed files under: ${PATHS[*]}"
  emit_output "changed=false"
  exit 0
fi

MAX_ATTEMPTS=5
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  git fetch origin main
  git reset --mixed origin/main
  add_existing "${PATHS[@]}"

  if git diff --cached --quiet; then
    echo "origin/main already matches every changed path (a concurrent push covered it)."
    emit_output "changed=false"
    exit 0
  fi

  git commit -m "Sync IEBC historical forms and OCR review data"

  if git push origin HEAD:main; then
    echo "Pushed on attempt $attempt."
    emit_output "changed=true"
    exit 0
  fi

  echo "Push rejected on attempt $attempt/$MAX_ATTEMPTS (origin advanced again); retrying..." >&2
  sleep "$((attempt * 3))"
done

echo "::error::Could not publish after $MAX_ATTEMPTS attempts -- origin/main kept advancing faster than this run could push. This run's regenerated files were NOT committed. The next scheduled run will regenerate them fresh from current portal state; nothing is permanently lost, but investigate why pushes are this frequent (another automation? repeated manual PUSH_TO_GITHUB.cmd runs?)." >&2
exit 1
