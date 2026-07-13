FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGINE_ROOT=/app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[s3]'
COPY . .
RUN mkdir -p data/raw data/state data/public data/review

CMD ["python", "-m", "olkalou_engine.cli", "--root", ".", "worker"]
