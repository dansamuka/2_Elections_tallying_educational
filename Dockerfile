FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGINE_ROOT=/app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# This single image builds all four docker-compose services (dashboard,
# review, worker-a, worker-b) -- `worker` runs the dual-cloud OCR extractor
# whenever OCR_MODE=dual-cloud, so google-cloud-vision/boto3 need to be here
# unconditionally, not installed later or assumed present. Previously only
# `[s3]` was installed: harmless while the ROI map is uncalibrated and
# OCR_MODE defaults to `none`, but the moment calibration finishes and
# dual-cloud is turned on for real, DualCloudExtractor's constructor would
# hit an ImportError and crash the worker outright, with no fallback (unlike
# the historical pipeline's `auto` mode, which now degrades gracefully).
# `[ocr]` already includes boto3, so this also covers what `[s3]` needs.
RUN pip install --no-cache-dir '.[ocr]'
COPY . .
RUN mkdir -p data/raw data/state data/public data/review

CMD ["python", "-m", "olkalou_engine.cli", "--root", ".", "worker"]
