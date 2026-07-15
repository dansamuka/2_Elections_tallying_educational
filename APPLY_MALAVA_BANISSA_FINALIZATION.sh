#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ -d .git ]] || { echo "Run from the cloned repository root." >&2; exit 1; }
python -m compileall -q src scripts
command -v node >/dev/null && node --check frontend/archive.js
python -m pytest -q
git add \
  .github/workflows/sync-historical-forms.yml .github/workflows/restore-historical-snapshot.yml \
  src/olkalou_engine/models.py src/olkalou_engine/portal.py src/olkalou_engine/archive.py \
  src/olkalou_engine/historical_ocr.py src/olkalou_engine/historical_identity.py src/olkalou_engine/cli.py \
  frontend/archive.js frontend/archive.html frontend/styles.css \
  scripts/validate_archive_form_links.py tests/test_malava_bootstrap.py tests/test_portal.py \
  RESTORE_LAST_GOOD_HISTORICAL_SYNC.cmd RESTORE_LAST_GOOD_HISTORICAL_SYNC.sh \
  MALAVA_BANISSA_ARCHIVE_FINALIZATION_14JUL2026.md
git commit -m "Finalize Malava hierarchy and restore Banissa form links" || true
git push origin main
if command -v gh >/dev/null; then
  gh workflow run restore-historical-snapshot.yml --ref main \
    -f snapshot_sha=b81eab0841661e5dc3deb86396b966181eac019a
  echo "Restore workflow dispatched."
else
  echo 'Run "Restore Banissa and Malava archive" once from GitHub Actions.'
fi
