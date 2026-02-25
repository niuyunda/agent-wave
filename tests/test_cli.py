from __future__ import annotations

import json
import runpy
import subprocess
import sys
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


def test_cli_module_entrypoint_help() -> None:
    old_argv = sys.argv[:]
    sys.argv = ["agvv", "--help"]
    try:
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("agvv.cli", run_name="__main__")
        assert exc_info.value.code == 0
    finally:
        sys.argv = old_argv


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
