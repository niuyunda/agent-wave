from __future__ import annotations

import json
import runpy
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agvv.cli import app


runner = CliRunner()


def test_cli_help_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "project" in result.stdout
    assert "feature" in result.stdout
    assert "orch" in result.stdout
    assert "pr" in result.stdout


def test_cli_project_init_and_feature_flow(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()

    init_result = runner.invoke(app, ["project", "init", "demo", "--base-dir", str(base)])
    assert init_result.exit_code == 0
    assert "Initialized:" in init_result.stdout

    start_result = runner.invoke(
        app,
        [
            "feature",
            "start",
            "demo",
            "feat-cli",
            "--base-dir",
            str(base),
            "--agent",
            "agent-a",
            "--task-id",
            "task-123",
            "--ticket",
            "ABC-1",
            "--param",
            "model=gpt",
            "--mkdir",
            "src",
        ],
    )
    assert start_result.exit_code == 0
    assert "Created feature worktree" in start_result.stdout

    metadata = json.loads((base / "demo" / "feat-cli" / ".agvv" / "context.json").read_text(encoding="utf-8"))
    assert metadata["agent"] == "agent-a"
    assert metadata["params"] == {"model": "gpt"}

    cleanup_result = runner.invoke(
        app, ["feature", "cleanup", "demo", "feat-cli", "--base-dir", str(base), "--keep-branch"]
    )
    assert cleanup_result.exit_code == 0
    assert "branch kept" in cleanup_result.stdout


def test_cli_feature_start_invalid_param_returns_error(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()

    runner.invoke(app, ["project", "init", "demo", "--base-dir", str(base)])

    result = runner.invoke(
        app,
        ["feature", "start", "demo", "feat-bad", "--base-dir", str(base), "--param", "not-kv"],
    )
    assert result.exit_code != 0
    assert "Invalid --param value" in result.stderr


def test_cli_project_adopt_non_repo_returns_error(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    src = tmp_path / "src"
    src.mkdir()

    result = runner.invoke(app, ["project", "adopt", str(src), "demo", "--base-dir", str(base)])
    assert result.exit_code != 0
    assert "git repository" in result.stderr


def test_cli_project_adopt_success(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    src = tmp_path / "src"
    src.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=src, check=True, capture_output=True, text=True)
    (src / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=src, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=src, check=True, capture_output=True, text=True)

    result = runner.invoke(app, ["project", "adopt", str(src), "demo", "--base-dir", str(base)])
    assert result.exit_code == 0
    assert "Adopted existing repo" in result.stdout
    assert (base / "demo" / "main").exists()


def test_cli_feature_cleanup_missing_repo_returns_error(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    result = runner.invoke(app, ["feature", "cleanup", "demo", "feat-x", "--base-dir", str(base)])
    assert result.exit_code != 0
    assert "Repo not found" in result.stderr


def test_cli_module_entrypoint_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["agvv", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("agvv.cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_cli_project_init_error_path(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    project_dir = base / "broken"
    project_dir.mkdir()
    # Force internal git calls to fail with an invalid repo.git path.
    (project_dir / "repo.git").write_text("not-a-git-dir", encoding="utf-8")

    result = runner.invoke(app, ["project", "init", "broken", "--base-dir", str(base)])
    assert result.exit_code != 0
    assert "Command failed: git -C" in result.stderr


def test_cli_orch_list_reads_tasks_registry(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-03-02T10:00:00+00:00",
                "tasks": [
                    {
                        "id": "t2",
                        "project_name": "calcproj",
                        "feature": "feat-sub",
                        "status": "failed",
                        "session": "tmux-2",
                        "agent": "codex",
                        "updated_at": "2026-03-02T10:02:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["orch", "list", "--tasks-path", str(tasks_path), "--status", "failed", "--project", "calcproj"],
    )
    assert result.exit_code == 0
    assert "t2" in result.stdout
    assert "calcproj/feat-sub" in result.stdout


def test_cli_orch_list_no_tasks(tmp_path: Path) -> None:
    result = runner.invoke(app, ["orch", "list", "--tasks-path", str(tmp_path / "missing.json")])
    assert result.exit_code == 0
    assert "No tasks found." in result.stdout


def test_cli_orch_spawn_invokes_core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeTask:
        id: str
        project_name: str
        feature: str
        status: str
        session: str | None
        agent: str | None
        updated_at: str

    captured: dict[str, str] = {}

    def _fake_create_orch_task(**kwargs):
        captured.update({k: str(v) for k, v in kwargs.items()})
        return _FakeTask(
            id=kwargs["task_id"],
            project_name=kwargs["project_name"],
            feature=kwargs["feature"],
            status="running",
            session=kwargs["session"],
            agent=kwargs["agent"],
            updated_at="2026-03-02T10:00:00+00:00",
        )

    monkeypatch.setattr("agvv.cli.create_orch_task", _fake_create_orch_task)

    result = runner.invoke(
        app,
        [
            "orch",
            "spawn",
            "demo",
            "feat-a",
            "--task-id",
            "task-1",
            "--session",
            "sess-1",
            "--agent",
            "codex",
            "--agent-cmd",
            "echo hi",
            "--base-dir",
            str(tmp_path),
            "--tasks-path",
            str(tmp_path / "tasks.json"),
        ],
    )

    assert result.exit_code == 0
    assert "Spawned task: task-1" in result.stdout
    assert captured["project_name"] == "demo"
    assert captured["feature"] == "feat-a"


def test_cli_pr_check_invokes_core(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class _FakeResult:
        status: str
        reason: str
        state: str
        review_decision: str | None

    monkeypatch.setattr(
        "agvv.cli.check_pr_status",
        lambda repo, pr_number: _FakeResult(
            status="waiting", reason="pending_review_or_ci", state="OPEN", review_decision=None
        ),
    )

    result = runner.invoke(app, ["pr", "check", "--repo", "owner/repo", "--pr", "12"])
    assert result.exit_code == 0
    assert "status=waiting" in result.stdout


def test_cli_pr_wait_invokes_core(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class _FakePr:
        status: str
        reason: str
        state: str
        review_decision: str | None

    @dataclass
    class _FakeWait:
        result: _FakePr
        attempts: int
        timed_out: bool

    monkeypatch.setattr(
        "agvv.cli.wait_pr_status",
        lambda repo, pr_number, interval_seconds, max_attempts: _FakeWait(
            result=_FakePr(
                status="needs_work", reason="changes_requested", state="OPEN", review_decision="CHANGES_REQUESTED"
            ),
            attempts=4,
            timed_out=False,
        ),
    )

    result = runner.invoke(
        app,
        ["pr", "wait", "--repo", "owner/repo", "--pr", "12", "--interval-seconds", "120", "--max-attempts", "30"],
    )
    assert result.exit_code == 0
    assert "status=needs_work" in result.stdout
    assert "attempts=4" in result.stdout
