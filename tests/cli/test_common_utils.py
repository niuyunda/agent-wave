"""Tests for shared CLI utility helpers (now inlined in cli.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from agvv.cli import _exit_error, _parse_state, _resolve_path
from agvv.runtime.models import TaskState
from agvv.shared.errors import AgvvError


def test_parse_state_accepts_none_and_valid_value() -> None:
    assert _parse_state(None) is None
    assert _parse_state("coding") == TaskState.CODING


def test_parse_state_rejects_invalid_value() -> None:
    with pytest.raises(typer.BadParameter, match="Unsupported --state value"):
        _parse_state("not-a-real-state")


def test_resolve_path_resolves_user_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/agvv-home")
    resolved = _resolve_path("~/tasks.db")
    assert resolved == Path("/tmp/agvv-home/tasks.db").resolve()


def test_resolve_path_returns_none_for_none_input() -> None:
    assert _resolve_path(None) is None


def test_exit_error_raises_typer_exit() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        _exit_error(AgvvError("boom"))
    assert exc_info.value.exit_code == 1
