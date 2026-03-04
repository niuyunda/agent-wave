"""CLI task command tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agvv.cli import app
from agvv.runtime.models import TaskState
from agvv.shared.errors import AgvvError


runner = CliRunner()


def test_cli_task_run_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        project_name: str
        feature: str
        session: str

    captured: dict[str, str | None] = {}

    def _fake_run_task_from_spec(
        spec_path: Path,
        db_path: Path | None,
        *,
        agent_provider: str | None = None,
        project_dir: Path | None = None,
    ):
        captured["spec_path"] = str(spec_path)
        captured["db_path"] = str(db_path)
        captured["agent_provider"] = agent_provider
        captured["project_dir"] = str(project_dir) if project_dir is not None else None
        return _FakeTask(id="task-1", state=TaskState.CODING, project_name="demo", feature="feat-a", session="sess-1")

    monkeypatch.setattr("agvv.cli.run_task_from_spec", _fake_run_task_from_spec)
    spec = tmp_path / "task.json"
    spec.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["task", "run", "--spec", str(spec), "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "Task started: task-1" in result.stdout
    assert str(spec.resolve()) == captured["spec_path"]
    assert captured["agent_provider"] is None
    assert captured["project_dir"] is None


def test_cli_task_run_forwards_agent_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        project_name: str
        feature: str
        session: str

    captured: dict[str, str | None] = {}

    def _fake_run_task_from_spec(
        spec_path: Path,
        db_path: Path | None,
        *,
        agent_provider: str | None = None,
        project_dir: Path | None = None,
    ):
        captured["agent_provider"] = agent_provider
        captured["project_dir"] = str(project_dir) if project_dir is not None else None
        return _FakeTask(id="task-2", state=TaskState.CODING, project_name="demo", feature="feat-b", session="sess-2")

    monkeypatch.setattr("agvv.cli.run_task_from_spec", _fake_run_task_from_spec)
    spec = tmp_path / "task.json"
    spec.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "task",
            "run",
            "--spec",
            str(spec),
            "--db-path",
            str(tmp_path / "tasks.db"),
            "--agent",
            "codex",
        ],
    )
    assert result.exit_code == 0
    assert "Task started: task-2" in result.stdout
    assert captured["agent_provider"] == "codex"
    assert captured["project_dir"] is None


def test_cli_task_run_forwards_project_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        project_name: str
        feature: str
        session: str

    captured: dict[str, str | None] = {}

    def _fake_run_task_from_spec(
        spec_path: Path,
        db_path: Path | None,
        *,
        agent_provider: str | None = None,
        project_dir: Path | None = None,
    ):
        captured["project_dir"] = str(project_dir) if project_dir is not None else None
        return _FakeTask(id="task-3", state=TaskState.CODING, project_name="demo", feature="feat-c", session="sess-3")

    monkeypatch.setattr("agvv.cli.run_task_from_spec", _fake_run_task_from_spec)
    spec = tmp_path / "task.json"
    spec.write_text("{}", encoding="utf-8")
    project_dir = tmp_path / "repo"
    project_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "task",
            "run",
            "--spec",
            str(spec),
            "--project-dir",
            str(project_dir),
        ],
    )
    assert result.exit_code == 0
    assert captured["project_dir"] == str(project_dir.resolve())


def test_cli_task_status_no_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.list_task_statuses", lambda db_path, state=None: [])
    result = runner.invoke(app, ["task", "status", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "No tasks found." in result.stdout


def test_cli_task_status_filters_by_task_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    result = runner.invoke(app, ["task", "status", "--db-path", str(tmp_path / "tasks.db"), "--task-id", "t2"])
    assert result.exit_code == 0
    assert "t2" in result.stdout
    assert "t1" not in result.stdout


def test_cli_task_retry_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState
        session: str

    monkeypatch.setattr(
        "agvv.cli.retry_task",
        lambda task_id, db_path, session: _FakeTask(id=task_id, state=TaskState.CODING, session=session or "sess-1"),
    )
    result = runner.invoke(app, ["task", "retry", "--task-id", "task-1", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "Task retried: task-1" in result.stdout


def test_cli_task_cleanup_invokes_tasking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        state: TaskState

    monkeypatch.setattr("agvv.cli.cleanup_task", lambda task_id, db_path, force: _FakeTask(id=task_id, state=TaskState.CLEANED))
    result = runner.invoke(app, ["task", "cleanup", "--task-id", "task-1", "--db-path", str(tmp_path / "tasks.db")])
    assert result.exit_code == 0
    assert "Task cleaned: task-1" in result.stdout


def test_cli_task_run_renders_agvv_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.run_task_from_spec", lambda *args, **kwargs: (_ for _ in ()).throw(AgvvError("invalid spec")))
    spec = tmp_path / "task.json"
    spec.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["task", "run", "--spec", str(spec)])
    assert result.exit_code == 1
    assert "invalid spec" in result.stderr
