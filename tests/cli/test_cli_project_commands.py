"""CLI project command tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agvv.cli import app
from agvv.shared.errors import AgvvError


runner = CliRunner()


def test_cli_project_init_invokes_orchestration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakePaths:
        repo_dir: Path
        main_dir: Path

    captured: dict[str, str] = {}

    def _fake_init_project(project_name: str, base_dir: Path) -> _FakePaths:
        captured["project_name"] = project_name
        captured["base_dir"] = str(base_dir)
        return _FakePaths(repo_dir=base_dir / project_name / "repo.git", main_dir=base_dir / project_name / "main")

    monkeypatch.setattr("agvv.cli.init_project", _fake_init_project)
    result = runner.invoke(app, ["project", "init", "--project-name", "demo", "--base-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Project initialized: demo" in result.stdout
    assert captured["project_name"] == "demo"
    assert captured["base_dir"] == str(tmp_path.resolve())


def test_cli_project_adopt_invokes_orchestration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakePaths:
        repo_dir: Path
        main_dir: Path

    captured: dict[str, str] = {}
    source_repo = tmp_path / "src"
    source_repo.mkdir()

    def _fake_adopt_project(existing_repo: Path, project_name: str, base_dir: Path) -> tuple[_FakePaths, str]:
        captured["existing_repo"] = str(existing_repo)
        captured["project_name"] = project_name
        captured["base_dir"] = str(base_dir)
        paths = _FakePaths(repo_dir=base_dir / project_name / "repo.git", main_dir=base_dir / project_name / "main")
        return paths, "main"

    monkeypatch.setattr("agvv.cli.adopt_project", _fake_adopt_project)
    result = runner.invoke(
        app,
        [
            "project",
            "adopt",
            "--project-name",
            "demo",
            "--repo",
            str(source_repo),
            "--base-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Project adopted: demo" in result.stdout
    assert "branch=main" in result.stdout
    assert captured["existing_repo"] == str(source_repo.resolve())
    assert captured["project_name"] == "demo"
    assert captured["base_dir"] == str(tmp_path.resolve())


def test_cli_project_adopt_renders_agvv_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.adopt_project", lambda *args, **kwargs: (_ for _ in ()).throw(AgvvError("invalid repo")))
    result = runner.invoke(
        app,
        [
            "project",
            "adopt",
            "--project-name",
            "demo",
            "--repo",
            str(tmp_path / "missing"),
            "--base-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "invalid repo" in result.stderr
