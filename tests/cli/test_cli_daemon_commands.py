"""CLI daemon command tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agvv.cli import app
from agvv.runtime.models import TaskState


runner = CliRunner()


def test_cli_daemon_run_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        updated_at: str

    monkeypatch.setattr(
        "agvv.cli.daemon_run_once",
        lambda db_path, max_workers=1: [_FakeTask(id="task-1", state=TaskState.RUNNING, updated_at="2026-03-03T10:00:00+00:00")],
    )
    result = runner.invoke(app, ["daemon", "run", "--once", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "reconciled=1" in result.stdout
    assert "task-1" in result.stdout


def test_cli_daemon_run_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.daemon_run_loop", lambda db_path, interval_seconds, max_loops, max_workers=1: 3)
    result = runner.invoke(
        app,
        ["daemon", "run", "--db-path", str(tmp_path / "tasks.db"), "--interval-seconds", "5", "--max-loops", "3"],
    )
    assert result.exit_code == 0
    assert "loops=3" in result.stdout


def test_cli_daemon_run_forwards_max_workers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, int] = {}

    def _fake_loop(db_path, interval_seconds, max_loops, max_workers=1):
        captured["max_workers"] = max_workers
        return 1

    monkeypatch.setattr("agvv.cli.daemon_run_loop", _fake_loop)
    result = runner.invoke(
        app,
        [
            "daemon",
            "run",
            "--db-path",
            str(tmp_path / "tasks.db"),
            "--interval-seconds",
            "5",
            "--max-loops",
            "1",
            "--max-workers",
            "4",
        ],
    )
    assert result.exit_code == 0
    assert captured["max_workers"] == 4


def test_cli_daemon_run_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.daemon_run_loop", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    result = runner.invoke(app, ["daemon", "run", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 130
    assert "daemon interrupted" in result.stdout
