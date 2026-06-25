"""Tests for the ExecutionModeManager (Manual / Copilot / Autopilot + persistence)."""

from __future__ import annotations

import importlib

import app.services.execution_mode as em
from app.services.execution_mode import ExecutionMode, ExecutionModeManager


def test_enum_values():
    assert ExecutionMode.MANUAL.value == "manual"
    assert ExecutionMode.COPILOT.value == "copilot"
    assert ExecutionMode.AUTOPILOT.value == "autopilot"


def test_default_mode_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "PERSIST_PATH", str(tmp_path / "missing.json"))
    mgr = ExecutionModeManager()
    assert mgr.mode == ExecutionMode.MANUAL


def test_set_mode_and_summary_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "PERSIST_PATH", str(tmp_path / "mode.json"))
    mgr = ExecutionModeManager()

    s = mgr.set_mode(ExecutionMode.AUTOPILOT)
    assert s["mode"] == "autopilot"
    assert s["auto_equity"] is True and s["auto_options"] is True
    assert s["needs_approval"] is False
    assert "description" in s and s["changed_by"] == "user"

    s2 = mgr.set_mode(ExecutionMode.COPILOT, by="tester")
    assert s2["needs_approval"] is True and s2["auto_equity"] is False
    assert s2["changed_by"] == "tester"

    s3 = mgr.summary()
    assert s3["mode"] == "copilot"


def test_persistence_round_trip(tmp_path, monkeypatch):
    path = str(tmp_path / "persist.json")
    monkeypatch.setattr(em, "PERSIST_PATH", path)
    ExecutionModeManager().set_mode(ExecutionMode.AUTOPILOT)
    # A fresh manager should restore the saved mode.
    restored = ExecutionModeManager()
    assert restored.mode == ExecutionMode.AUTOPILOT


def test_save_failure_is_non_fatal(tmp_path, monkeypatch):
    # Point at an unwritable directory path → _save swallows the error.
    monkeypatch.setattr(em, "PERSIST_PATH", "/nonexistent_dir/exec_mode.json")
    mgr = ExecutionModeManager()
    out = mgr.set_mode(ExecutionMode.COPILOT)   # must not raise
    assert out["mode"] == "copilot"
