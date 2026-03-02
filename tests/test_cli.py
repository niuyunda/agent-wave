"""CLI behavior tests for task/daemon command surface."""

from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agvv.cli import app
from agvv.tasking import TaskState


runner = CliRunner()


def test_cli_help_only_new_commands() -> None:
    """Show top-level help and ensure only new command groups are exposed."""

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "task" in result.stdout
    assert "daemon" in result.stdout
    assert "│ project" not in result.stdout
    assert "│ feature" not in result.stdout
    assert "│ orch" not in result.stdout
    assert "│ pr" not in result.stdout


def test_cli_task_help_commands() -> None:
    """Show task help and verify expected subcommands are listed."""

    result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "status" in result.stdout
    assert "retry" in result.stdout
    assert "cleanup" in result.stdout


def test_cli_daemon_help_commands() -> None:
    """Show daemon help and verify the run command is listed."""

    result = runner.invoke(app, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout


def test_cli_module_entrypoint_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute module entrypoint with --help and expect clean exit."""

    monkeypatch.setattr(sys, "argv", ["agvv", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("agvv.cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_cli_task_run_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invoke task run command and ensure tasking adapter receives paths."""

    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        project_name: str
        feature: str
        session: str

    captured: dict[str, str] = {}

    def _fake_run_task_from_spec(spec_path: Path, db_path: Path | None):
        captured["spec_path"] = str(spec_path)
        captured["db_path"] = str(db_path)
        return _FakeTask(
            id="task-1",
            state=TaskState.CODING,
            project_name="demo",
            feature="feat-a",
            session="sess-1",
        )

    monkeypatch.setattr("agvv.cli.run_task_from_spec", _fake_run_task_from_spec)
    spec = tmp_path / "task.json"
    spec.write_text("{}", encoding="utf-8")

    result = runner.invoke(
        app,
        ["task", "run", "--spec", str(spec), "--db-path", str(tmp_path / "tasks.db")],
    )
    assert result.exit_code == 0
    assert "Task started: task-1" in result.stdout
    assert str(spec.resolve()) == captured["spec_path"]


def test_cli_task_status_no_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Print friendly message when status query returns no tasks."""

    monkeypatch.setattr("agvv.cli.list_task_statuses", lambda db_path, state=None: [])
    result = runner.invoke(app, ["task", "status", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "No tasks found." in result.stdout


def test_cli_task_status_filters_by_task_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Filter status output by task id at CLI layer."""

    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        project_name: str
        feature: str
        session: str
        pr_number: int | None
        repair_cycles: int
        last_error: str | None
        updated_at: str

    monkeypatch.setattr(
        "agvv.cli.list_task_statuses",
        lambda db_path, state=None: [
            _FakeTask(
                id="t1",
                state=TaskState.CODING,
                project_name="demo",
                feature="feat-a",
                session="s1",
                pr_number=None,
                repair_cycles=0,
                last_error=None,
                updated_at="2026-03-03T00:00:00+00:00",
            ),
            _FakeTask(
                id="t2",
                state=TaskState.FAILED,
                project_name="demo",
                feature="feat-b",
                session="s2",
                pr_number=7,
                repair_cycles=2,
                last_error="boom",
                updated_at="2026-03-03T00:00:01+00:00",
            ),
        ],
    )
    result = runner.invoke(
        app,
        ["task", "status", "--db-path", str(tmp_path / "tasks.db"), "--task-id", "t2"],
    )
    assert result.exit_code == 0
    assert "t2" in result.stdout
    assert "t1" not in result.stdout


def test_cli_task_retry_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invoke task retry command and forward args to tasking layer."""

    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        session: str

    monkeypatch.setattr(
        "agvv.cli.retry_task",
        lambda task_id, db_path, session: _FakeTask(id=task_id, state=TaskState.CODING, session=session or "sess-1"),
    )
    result = runner.invoke(
        app,
        ["task", "retry", "--task-id", "task-1", "--db-path", str(tmp_path / "tasks.db")],
    )
    assert result.exit_code == 0
    assert "Task retried: task-1" in result.stdout


def test_cli_task_cleanup_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invoke task cleanup command and print resulting state."""

    @dataclass
    class _FakeTask:
        id: str
        state: TaskState

    monkeypatch.setattr(
        "agvv.cli.cleanup_task",
        lambda task_id, db_path, force: _FakeTask(id=task_id, state=TaskState.CLEANED),
    )
    result = runner.invoke(
        app,
        ["task", "cleanup", "--task-id", "task-1", "--db-path", str(tmp_path / "tasks.db")],
    )
    assert result.exit_code == 0
    assert "Task cleaned: task-1" in result.stdout


def test_cli_daemon_run_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run daemon once mode and render reconciled task lines."""

    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        updated_at: str

    monkeypatch.setattr(
        "agvv.cli.daemon_run_once",
        lambda db_path: [_FakeTask(id="task-1", state=TaskState.CODING, updated_at="2026-03-03T10:00:00+00:00")],
    )
    result = runner.invoke(app, ["daemon", "run", "--once", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "reconciled=1" in result.stdout
    assert "task-1" in result.stdout


def test_cli_daemon_run_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run daemon loop mode and print terminal loop count."""

    monkeypatch.setattr("agvv.cli.daemon_run_loop", lambda db_path, interval_seconds, max_loops: 3)
    result = runner.invoke(
        app,
        ["daemon", "run", "--db-path", str(tmp_path / "tasks.db"), "--interval-seconds", "5", "--max-loops", "3"],
    )
    assert result.exit_code == 0
    assert "loops=3" in result.stdout
