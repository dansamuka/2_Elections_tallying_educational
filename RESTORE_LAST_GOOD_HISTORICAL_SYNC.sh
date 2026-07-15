#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
SNAPSHOT="${1:-b81eab0841661e5dc3deb86396b966181eac019a}"
git fetch origin main
git checkout -B main origin/main
git cat-file -e "$SNAPSHOT^{commit}"
git checkout "$SNAPSHOT" -- \
  data/elections/banissa-2025 data/elections/malava-2025 \
  data/public/elections/banissa-2025.json data/public/elections/malava-2025.json \
  data/public/elections/banissa-2025 data/public/elections/malava-2025
python -m olkalou_engine.cli --root . archive-remap malava-2025
python -m olkalou_engine.cli --root . archive-ocr malava-2025 --engine embedded
python -m olkalou_engine.cli --root . archive-build malava-2025
python -m olkalou_engine.cli --root . archive-build banissa-2025
git add data/elections/banissa-2025 data/elections/malava-2025 \
  data/public/elections/banissa-2025.json data/public/elections/malava-2025.json \
  data/public/elections/banissa-2025 data/public/elections/malava-2025 \
  data/public/elections/catalog.json
git commit -m "Restore Banissa PDFs and finalize Malava hierarchy" || true
git push origin main
