"""Runtime usecase-level tests for run/retry/cleanup/query flows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agvv.orchestration import layout_paths
from agvv.runtime.models import TaskSpec, TaskState
from agvv.runtime.store import TaskStore
from agvv.runtime.core import (
    cleanup_task,
    list_task_statuses,
    retry_task,
    run_task_from_spec,
)
from agvv.shared.errors import AgvvError


def _write_spec(path: Path, payload: dict) -> Path:
    payload_copy = payload.copy()
    body = str(
        payload_copy.pop(
            "requirements", "# Task Doc\n\n- Implement required changes.\n"
        )
    ).strip()

    def _yaml_scalar(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value)
        if (
            text == ""
            or text != text.strip()
            or ":" in text
            or "#" in text
            or text.startswith(("[", "{", "-", "!", "&", "*", "@", "`", '"', "'"))
        ):
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return text

    lines: list[str] = []
    for key, value in payload_copy.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_yaml_scalar(item)}")
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")

    front_matter = "\n".join(lines)
    path.write_text(
        f"---\n{front_matter}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _patch_session_launch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    start_feature=lambda **kwargs: None,
    tmux_session_exists=lambda _session: False,
    tmux_new_session=lambda _session, _cwd, _command: None,
    tmux_pipe_pane=lambda _session, _output_log_path: None,
) -> None:
    monkeypatch.setattr("agvv.orchestration.start_feature", start_feature)
    monkeypatch.setattr("agvv.orchestration.tmux_session_exists", tmux_session_exists)
    monkeypatch.setattr("agvv.orchestration.tmux_new_session", tmux_new_session)
    monkeypatch.setattr("agvv.orchestration.tmux_pipe_pane", tmux_pipe_pane)


def test_task_store_create_and_list(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="taskA",
        project_name="demo",
        feature="featA",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    assert created.state == TaskState.PENDING
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].id == "taskA"


def test_run_task_from_spec_starts_coding_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task.md",
        {
            "task_id": "task_run",
            "project_name": "demo",
            "feature": "feat_run",
            "agent_cmd": "echo run",
            "base_dir": str(tmp_path),
        },
    )
    launched: list[str] = []
    repo_dir = tmp_path / "demo" / "repo.git"
    main_dir = tmp_path / "demo" / "main"
    repo_dir.mkdir(parents=True, exist_ok=True)
    main_dir.mkdir(parents=True, exist_ok=True)

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    _patch_session_launch(
        monkeypatch,
        start_feature=_fake_start_feature,
        tmux_new_session=lambda session, cwd, command: launched.append(
            f"{session}:{cwd}:{command}"
        ),
    )

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert task.state == TaskState.RUNNING
    assert launched
    assert "bash -lc" in launched[0]
    feature_dir = tmp_path / "demo" / "feat_run"
    assert (feature_dir / ".agvv" / "rendered_prompt.md").exists()
    assert (feature_dir / ".agvv" / "input_snapshot.json").exists()


def test_run_task_from_spec_applies_agent_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-override.md",
        {
            "task_id": "task_override",
            "project_name": "demo",
            "feature": "feat_override",
            "agent_cmd": "echo from-spec",
            "base_dir": str(tmp_path),
        },
    )
    launched: list[str] = []
    piped: list[str] = []
    repo_dir = tmp_path / "demo" / "repo.git"
    main_dir = tmp_path / "demo" / "main"
    repo_dir.mkdir(parents=True, exist_ok=True)
    main_dir.mkdir(parents=True, exist_ok=True)

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    _patch_session_launch(
        monkeypatch,
        start_feature=_fake_start_feature,
        tmux_new_session=lambda _session, _cwd, command: launched.append(command),
        tmux_pipe_pane=lambda _session, output_log_path: piped.append(
            str(output_log_path)
        ),
    )

    task = run_task_from_spec(
        spec_path=spec_path,
        db_path=tmp_path / "tasks.db",
        agent_provider="codex",
    )
    assert task.state == TaskState.RUNNING
    assert len(launched) == 1
    assert launched[0].startswith("bash -lc ")
    assert "codex" in launched[0]
    assert "rendered_prompt.md" in launched[0]
    assert "tee -a" not in launched[0]
    assert len(piped) == 1
    assert piped[0].endswith("agent_output.log")
    assert task.spec.agent == "codex"
    assert task.spec.agent_model is None


def test_run_task_from_spec_rejects_invalid_agent_override(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-invalid-override.md",
        {
            "task_id": "task_invalid_override",
            "project_name": "demo",
            "feature": "feat_invalid_override",
            "agent_cmd": "echo from-spec",
            "base_dir": str(tmp_path),
        },
    )
    with pytest.raises(AgvvError, match="Unsupported agent provider"):
        run_task_from_spec(
            spec_path=spec_path,
            db_path=tmp_path / "tasks.db",
            agent_provider="not-real",
        )


def test_run_task_from_spec_rejects_missing_requirements_text(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-missing-requirements.md"
    spec_path.write_text(
        "---\nproject_name: demo\nfeature: feat_missing_doc\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="requirements"):
        run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")


def test_run_task_from_spec_rejects_non_markdown_spec_file(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-bad-spec.json"
    spec_path.write_text(
        json.dumps({"project_name": "demo", "feature": "feat_bad_doc"}),
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="Markdown"):
        run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")


def test_run_task_from_spec_ignores_spec_base_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-ignore-base-dir.md",
        {
            "task_id": "task_ignore_base_dir",
            "project_name": "demo",
            "feature": "feat_ignore_base_dir",
            "agent_cmd": "echo run",
            "base_dir": str(tmp_path / "should_not_be_used"),
        },
    )
    seen: dict[str, Path] = {}

    def _fake_init_project(project_name: str, base_dir: Path):
        seen["base_dir"] = base_dir
        repo_dir = base_dir / project_name / "repo.git"
        main_dir = base_dir / project_name / "main"
        repo_dir.mkdir(parents=True, exist_ok=True)
        main_dir.mkdir(parents=True, exist_ok=True)

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.orchestration.init_project", _fake_init_project)
    _patch_session_launch(monkeypatch, start_feature=_fake_start_feature)

    run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert seen["base_dir"] == tmp_path.resolve()


def test_run_task_from_spec_auto_inits_project_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-auto-init.md",
        {
            "task_id": "task_auto_init",
            "project_name": "demo",
            "feature": "feat_auto_init",
            "agent_cmd": "echo from-spec",
            "base_dir": str(tmp_path),
        },
    )
    started = {"init": False}

    def _fake_init_project(project_name: str, base_dir: Path):
        started["init"] = True
        repo_dir = base_dir / project_name / "repo.git"
        main_dir = base_dir / project_name / "main"
        repo_dir.mkdir(parents=True, exist_ok=True)
        main_dir.mkdir(parents=True, exist_ok=True)

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.orchestration.init_project", _fake_init_project)
    _patch_session_launch(monkeypatch, start_feature=_fake_start_feature)

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert started["init"] is True
    assert task.state == TaskState.RUNNING


def test_run_task_from_spec_auto_adopts_existing_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-auto-adopt.md",
        {
            "task_id": "task_auto_adopt",
            "project_name": "demo",
            "feature": "feat_auto_adopt",
            "agent_cmd": "echo from-spec",
            "base_dir": str(tmp_path),
        },
    )
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir(parents=True, exist_ok=True)
    (source_repo / ".git").mkdir(parents=True, exist_ok=True)
    adopted = {"called": False}

    def _fake_adopt_project(existing_repo: Path, project_name: str, base_dir: Path):
        adopted["called"] = True
        assert existing_repo == source_repo.resolve()
        repo_dir = base_dir / project_name / "repo.git"
        main_dir = base_dir / project_name / "main"
        repo_dir.mkdir(parents=True, exist_ok=True)
        main_dir.mkdir(parents=True, exist_ok=True)
        return (
            type(
                "L",
                (),
                {"repo_dir": repo_dir, "main_dir": main_dir, "feature_dir": None},
            )(),
            "main",
        )

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.orchestration.adopt_project", _fake_adopt_project)
    _patch_session_launch(monkeypatch, start_feature=_fake_start_feature)

    task = run_task_from_spec(
        spec_path=spec_path, db_path=tmp_path / "tasks.db", project_dir=source_repo
    )
    assert adopted["called"] is True
    assert task.state == TaskState.RUNNING


def test_retry_task_relaunches_when_session_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_retry",
        project_name="demo",
        feature="feat_retry",
        agent_cmd="echo run",
        base_dir=tmp_path,
        session="sess-retry",
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id,
        state=TaskState.FAILED,
        last_error="boom",
        finished_at="2026-03-03T00:00:00+00:00",
    )
    (tmp_path / "demo" / "feat_retry").mkdir(parents=True, exist_ok=True)

    _patch_session_launch(monkeypatch)

    retried = retry_task(task_id="task_retry", db_path=tmp_path / "tasks.db")
    assert retried.state == TaskState.RUNNING
    assert retried.last_error is None
    assert retried.finished_at is None


def test_retry_task_force_restart_kills_existing_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_retry_force",
        project_name="demo",
        feature="feat_retry_force",
        agent_cmd="echo run",
        base_dir=tmp_path,
        session="sess-force",
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.RUNNING, started_at="2026-03-03T00:00:00+00:00"
    )
    (tmp_path / "demo" / "feat_retry_force").mkdir(parents=True, exist_ok=True)

    called: dict[str, bool] = {"killed": False}
    session_live: dict[str, bool] = {"value": True}
    _patch_session_launch(
        monkeypatch, tmux_session_exists=lambda _session: session_live["value"]
    )
    monkeypatch.setattr(
        "agvv.orchestration.tmux_kill_session",
        lambda _session: (
            called.__setitem__("killed", True),
            session_live.__setitem__("value", False),
        ),
    )

    retried = retry_task(
        task_id="task_retry_force", db_path=tmp_path / "tasks.db", force_restart=True
    )
    assert called["killed"] is True
    assert retried.state == TaskState.RUNNING
    assert retried.finished_at is None


def test_retry_task_rejects_non_recoverable_state(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_non_retryable",
        project_name="demo",
        feature="feat_non_retryable",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.DONE, finished_at="2026-03-03T01:00:00+00:00"
    )
    with pytest.raises(AgvvError, match="Cannot retry task in state: done"):
        retry_task(task_id="task_non_retryable", db_path=tmp_path / "tasks.db")


def test_cleanup_task_marks_cleaned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_clean",
        project_name="demo",
        feature="feat_clean",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    store.create_task(spec)
    monkeypatch.setattr(
        "agvv.orchestration.tmux_session_exists", lambda _session: False
    )
    monkeypatch.setattr(
        "agvv.orchestration.cleanup_feature",
        lambda project_name, feature, base_dir, delete_branch: None,
    )
    cleaned = cleanup_task("task_clean", db_path=tmp_path / "tasks.db")
    assert cleaned.state == TaskState.CLEANED


def test_cleanup_task_preserves_last_error_for_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_clean_error",
        project_name="demo",
        feature="feat_clean_error",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.FAILED, last_error="session timeout")
    monkeypatch.setattr(
        "agvv.orchestration.tmux_session_exists", lambda _session: False
    )
    monkeypatch.setattr(
        "agvv.orchestration.cleanup_feature",
        lambda project_name, feature, base_dir, delete_branch: None,
    )
    cleaned = cleanup_task("task_clean_error", db_path=tmp_path / "tasks.db")
    assert cleaned.state == TaskState.CLEANED
    assert cleaned.last_error == "session timeout"


def test_cleanup_task_force_deletes_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_force_clean",
        project_name="demo",
        feature="feat_force_clean",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    paths = layout_paths(
        created.project_name, created.spec.base_dir, feature=created.feature
    )
    paths.repo_dir.mkdir(parents=True, exist_ok=True)
    if paths.feature_dir is not None:
        paths.feature_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, bool] = {}

    def _fake_cleanup_force(
        project_name: str, feature: str, base_dir: Path, delete_branch: bool
    ) -> None:
        captured["delete_branch"] = delete_branch

    monkeypatch.setattr(
        "agvv.orchestration.tmux_session_exists", lambda _session: False
    )
    monkeypatch.setattr("agvv.orchestration.cleanup_feature_force", _fake_cleanup_force)

    cleaned = cleanup_task(created.id, db_path=tmp_path / "tasks.db", force=True)
    assert cleaned.state == TaskState.CLEANED
    assert captured["delete_branch"] is True


def test_list_task_statuses_filters_state(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_list",
        project_name="demo",
        feature="feat_list",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.CLEANED, finished_at=created.created_at
    )
    only_cleaned = list_task_statuses(tmp_path / "tasks.db", state=TaskState.CLEANED)
    assert len(only_cleaned) == 1
    assert only_cleaned[0].id == "task_list"
