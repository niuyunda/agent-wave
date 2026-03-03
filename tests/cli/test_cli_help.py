"""CLI help and entrypoint behavior tests."""

from __future__ import annotations

import runpy
import sys

import pytest
from typer.testing import CliRunner

from agvv.cli import app


runner = CliRunner()


def test_cli_help_only_new_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "task" in result.stdout
    assert "daemon" in result.stdout
    assert "│ project" not in result.stdout
    assert "│ feature" not in result.stdout
    assert "│ orch" not in result.stdout
    assert "│ pr" not in result.stdout


def test_cli_task_help_commands() -> None:
    result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "status" in result.stdout
    assert "retry" in result.stdout
    assert "cleanup" in result.stdout


def test_cli_daemon_help_commands() -> None:
    result = runner.invoke(app, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout


def test_cli_module_entrypoint_help(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("agvv.cli", None)
    monkeypatch.setattr(sys, "argv", ["agvv", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("agvv.cli", run_name="__main__")
    assert exc_info.value.code == 0
