"""Tests for the provider-agnostic LLM layer (mocked clients — no network)."""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from app.services.llm_provider import (
    DEFAULT_ANTHROPIC_MODEL, DEFAULT_GEMINI_MODEL, LLMUnavailable,
    build_messages, complete_anthropic, complete_gemini, generate,
    resolve_provider,
)


# ── resolve_provider ───────────────────────────────────────────────────────────────
def test_resolve_explicit_gemini():
    assert resolve_provider("gemini", None, "gkey") == "gemini"


def test_resolve_explicit_anthropic():
    assert resolve_provider("anthropic", "akey", None) == "anthropic"


def test_resolve_explicit_missing_key_raises():
    with pytest.raises(LLMUnavailable):
        resolve_provider("gemini", "akey", None)
    with pytest.raises(LLMUnavailable):
        resolve_provider("anthropic", None, "gkey")


def test_resolve_auto_prefers_gemini():
    assert resolve_provider("auto", "akey", "gkey") == "gemini"
    assert resolve_provider(None, "akey", "gkey") == "gemini"


def test_resolve_auto_falls_back_to_anthropic():
    assert resolve_provider("auto", "akey", None) == "anthropic"


def test_resolve_auto_no_keys_raises():
    with pytest.raises(LLMUnavailable):
        resolve_provider("auto", None, None)


# ── build_messages ─────────────────────────────────────────────────────────────────
def test_build_messages_grounds_in_data():
    system, prompt = build_messages("Why is X down?", "DATA HERE")
    assert "ONLY from the DATA" in system
    assert "DATA HERE" in prompt and "Why is X down?" in prompt


# ── complete_* with injected clients ────────────────────────────────────────────────
def test_complete_gemini_uses_client():
    client = MagicMock()
    client.models.generate_content.return_value = NS(text="  hello  ")
    out = complete_gemini("sys", "prompt", "gemini-2.5-flash", "k", client=client)
    assert out == "hello"
    client.models.generate_content.assert_called_once()


def test_complete_gemini_none_text():
    client = MagicMock()
    client.models.generate_content.return_value = NS(text=None)
    assert complete_gemini("s", "p", "m", "k", client=client) == ""


def test_complete_anthropic_uses_client():
    client = MagicMock()
    client.messages.create.return_value = NS(content=[NS(text="  answer ")])
    out = complete_anthropic("sys", "prompt", "claude-x", "k", client=client)
    assert out == "answer"
    client.messages.create.assert_called_once()


# ── generate (end to end with injected client) ──────────────────────────────────────
def test_generate_gemini_path():
    client = MagicMock()
    client.models.generate_content.return_value = NS(text="gem answer")
    out = generate("q", "ctx", provider="gemini", anthropic_key=None,
                   gemini_key="gkey", client=client)
    assert out["provider"] == "gemini"
    assert out["model"] == DEFAULT_GEMINI_MODEL
    assert out["answer"] == "gem answer"


def test_generate_anthropic_path_with_model_override():
    client = MagicMock()
    client.messages.create.return_value = NS(content=[NS(text="claude answer")])
    out = generate("q", "ctx", provider="anthropic", anthropic_key="akey",
                   gemini_key=None, model="claude-custom", client=client)
    assert out["provider"] == "anthropic" and out["model"] == "claude-custom"
    assert out["answer"] == "claude answer"


def test_generate_no_key_raises():
    with pytest.raises(LLMUnavailable):
        generate("q", "ctx", provider="auto", anthropic_key=None, gemini_key=None)


def test_default_models_sane():
    assert "gemini" in DEFAULT_GEMINI_MODEL
    assert "claude" in DEFAULT_ANTHROPIC_MODEL
