from __future__ import annotations

from pathlib import Path

import pytest
import typer

from agvv.commands.common import exit_with_agvv_error, parse_task_state, resolve_optional_path
from agvv.runtime.models import TaskState
from agvv.shared.errors import AgvvError


def test_parse_task_state_accepts_none_and_valid_value() -> None:
    assert parse_task_state(None) is None
    assert parse_task_state("coding") == TaskState.CODING


def test_parse_task_state_rejects_invalid_value() -> None:
    with pytest.raises(typer.BadParameter, match="Unsupported --state value"):
        parse_task_state("not-a-real-state")


def test_resolve_optional_path_resolves_user_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/agvv-home")
    resolved = resolve_optional_path("~/tasks.db")
    assert resolved == Path("/tmp/agvv-home/tasks.db").resolve()


def test_exit_with_agvv_error_raises_typer_exit() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        exit_with_agvv_error(AgvvError("boom"))
    assert exc_info.value.exit_code == 1
