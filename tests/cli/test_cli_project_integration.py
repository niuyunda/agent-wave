"""End-to-end CLI integration tests for project commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agvv.cli import app


runner = CliRunner()


def _git(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *cmd], cwd=cwd, text=True, capture_output=True, check=True)


def _create_source_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", branch], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test User"], cwd=path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "init repo"], cwd=path)
    return path


def test_cli_project_init_end_to_end(tmp_path: Path) -> None:
    base_dir = tmp_path / "workspace"
    result = runner.invoke(
        app,
        [
            "project",
            "init",
            "--project-name",
            "demo",
            "--base-dir",
            str(base_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Project initialized: demo" in result.stdout

    repo_dir = base_dir / "demo" / "repo.git"
    main_dir = base_dir / "demo" / "main"
    assert repo_dir.exists()
    assert main_dir.exists()

    head = subprocess.run(
        ["git", "-C", str(main_dir), "rev-parse", "--verify", "HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert head.returncode == 0


def test_cli_project_adopt_end_to_end(tmp_path: Path) -> None:
    source_repo = _create_source_repo(tmp_path / "source", branch="main")
    base_dir = tmp_path / "workspace"
    result = runner.invoke(
        app,
        [
            "project",
            "adopt",
            "--project-name",
            "adopted",
            "--repo",
            str(source_repo),
            "--base-dir",
            str(base_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Project adopted: adopted" in result.stdout
    assert "branch=main" in result.stdout

    repo_dir = base_dir / "adopted" / "repo.git"
    main_dir = base_dir / "adopted" / "main"
    assert repo_dir.exists()
    assert main_dir.exists()
    assert (main_dir / "README.md").read_text(encoding="utf-8") == "hello\n"
