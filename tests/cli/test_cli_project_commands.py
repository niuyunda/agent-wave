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
    class _FakeLayoutPaths:
        project_dir: Path
        repo_dir: Path
        main_dir: Path
        feature_dir: Path | None = None

    captured: dict[str, str] = {}

    def _fake_init_project(project_name: str, base_dir: Path):
        captured["project_name"] = project_name
        captured["base_dir"] = str(base_dir)
        project_dir = base_dir / project_name
        return _FakeLayoutPaths(
            project_dir=project_dir,
            repo_dir=project_dir / "repo.git",
            main_dir=project_dir / "main",
        )

    monkeypatch.setattr("agvv.cli.init_project", _fake_init_project)
    result = runner.invoke(app, ["project", "init", "demo", "--base-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Project initialized: demo" in result.stdout
    assert captured["project_name"] == "demo"
    assert captured["base_dir"] == str(tmp_path.resolve())


def test_cli_project_adopt_invokes_orchestration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    @dataclass
    class _FakeLayoutPaths:
        project_dir: Path
        repo_dir: Path
        main_dir: Path
        feature_dir: Path | None = None

    captured: dict[str, str] = {}

    def _fake_adopt_project(existing_repo: Path, project_name: str, base_dir: Path):
        captured["existing_repo"] = str(existing_repo)
        captured["project_name"] = project_name
        captured["base_dir"] = str(base_dir)
        project_dir = base_dir / project_name
        return (
            _FakeLayoutPaths(
                project_dir=project_dir,
                repo_dir=project_dir / "repo.git",
                main_dir=project_dir / "main",
            ),
            "main",
        )

    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    monkeypatch.setattr("agvv.cli.adopt_project", _fake_adopt_project)
    result = runner.invoke(
        app,
        [
            "project",
            "adopt",
            "demo",
            "--existing-repo",
            str(source_repo),
            "--base-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert "Project adopted: demo" in result.stdout
    assert "branch=main" in result.stdout
    assert captured["project_name"] == "demo"
    assert captured["existing_repo"] == str(source_repo.resolve())
    assert captured["base_dir"] == str(tmp_path.resolve())


def test_cli_project_adopt_renders_agvv_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.cli.adopt_project", lambda *args, **kwargs: (_ for _ in ()).throw(AgvvError("bad repo")))
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    result = runner.invoke(app, ["project", "adopt", "demo", "--existing-repo", str(source_repo)])
    assert result.exit_code == 1
    assert "bad repo" in result.stderr
