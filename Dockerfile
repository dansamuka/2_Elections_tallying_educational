FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGINE_ROOT=/app

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
# The realtime service executes the historical, field-isolated OCR pipeline.
# Install it once into the long-lived image instead of repeating apt/pip work
# for every GitHub Actions run.
RUN pip install --no-cache-dir '.[historical-ocr,pdf]'
COPY . .
RUN mkdir -p data/raw data/state data/public data/review data/public/realtime/status

CMD ["python", "-m", "olkalou_engine.cli", "--root", ".", "realtime-api"]
