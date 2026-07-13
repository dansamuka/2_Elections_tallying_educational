"""Regression coverage for the 13 Jul 2026 auth-bypass fix in review_api.py.

Before the fix, create_app() would silently disable ALL authentication
whenever REVIEW_API_TOKEN was left at its default "change-me" -- meaning an
operator who forgot to set a real token would unknowingly run the review
console (which can publish election results) with zero auth, reachable on
every network interface (REVIEW_HOST defaults to 0.0.0.0). These tests
pin the corrected behaviour: refuse to start on the default token, and
always enforce a real token once configured.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from olkalou_engine.config import Settings
from olkalou_engine.review_api import create_app

ROOT = Path(__file__).parents[1]


def _settings(token: str) -> Settings:
    return Settings(ENGINE_ROOT=ROOT, REVIEW_API_TOKEN=token)


def test_create_app_refuses_default_token():
    settings = _settings("change-me")
    with pytest.raises(RuntimeError, match="change-me"):
        create_app(settings)


def test_create_app_starts_with_real_token():
    settings = _settings("a-real-secret-token")
    app = create_app(settings)
    assert app is not None


def test_health_endpoint_requires_no_auth():
    """Health check stays open (no election data), everything else does not."""
    settings = _settings("a-real-secret-token")
    app = create_app(settings)
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_protected_endpoint_rejects_missing_token():
    settings = _settings("a-real-secret-token")
    app = create_app(settings)
    client = TestClient(app)
    resp = client.get("/api/reference")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_wrong_token():
    settings = _settings("a-real-secret-token")
    app = create_app(settings)
    client = TestClient(app)
    resp = client.get("/api/reference", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_protected_endpoint_accepts_correct_token():
    settings = _settings("a-real-secret-token")
    app = create_app(settings)
    client = TestClient(app)
    resp = client.get("/api/reference", headers={"Authorization": "Bearer a-real-secret-token"})
    assert resp.status_code == 200
