"""Tests for API key dependencies and kill-switch reset code config."""

import pytest
from fastapi import HTTPException

from app.api.deps import require_api_key, require_api_key_configured


def test_require_api_key_skips_when_secret_unset(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.secret_key", "")
    require_api_key("")  # must not raise


def test_require_api_key_rejects_mismatch(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.secret_key", "prod-secret")
    with pytest.raises(HTTPException) as exc:
        require_api_key("wrong")
    assert exc.value.status_code == 403


def test_require_api_key_accepts_match(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.secret_key", "prod-secret")
    require_api_key("prod-secret")


def test_require_api_key_configured_needs_secret(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.secret_key", "")
    with pytest.raises(HTTPException) as exc:
        require_api_key_configured("")
    assert exc.value.status_code == 503
