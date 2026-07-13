from __future__ import annotations

from typing import Any

import httpx


class AlertSink:
    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, details: dict[str, Any] | None = None) -> None:
        if not self.webhook_url:
            return
        payload = {
            "text": f"[{title}] {message}",
            "title": title,
            "message": message,
            "details": details or {},
        }
        try:
            httpx.post(self.webhook_url, json=payload, timeout=10).raise_for_status()
        except Exception:
            # Alert delivery must never crash the ingestion worker.
            pass
