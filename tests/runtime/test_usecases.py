"""Runtime usecase-level tests for run/retry/cleanup/query flows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agvv.orchestration import layout_paths
from agvv.runtime.models import TaskSpec, TaskState
from agvv.runtime.store import TaskStore
from agvv.runtime.usecases import cleanup_task, list_task_statuses, retry_task, run_task_from_spec
from agvv.shared.errors import AgvvError


def _write_spec(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_task_store_create_and_list(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="taskA",
        project_name="demo",
        feature="featA",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    assert created.state == TaskState.PENDING
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].id == "taskA"


def test_run_task_from_spec_starts_coding_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task.json",
        {
            "task_id": "task_run",
            "project_name": "demo",
            "feature": "feat_run",
            "agent_cmd": "echo run",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    launched: list[str] = []

    def _fake_start_feature(**kwargs):
        feature_dir = Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature", _fake_start_feature)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda session, cwd, command: launched.append(f"{session}:{cwd}:{command}"),
    )

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert task.state == TaskState.CODING
    assert launched


def test_run_task_from_spec_applies_agent_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-override.json",
        {
            "task_id": "task_override",
            "project_name": "demo",
            "feature": "feat_override",
            "agent_cmd": "echo from-spec",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    launched: list[str] = []

    def _fake_start_feature(**kwargs):
        feature_dir = Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature", _fake_start_feature)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _session, _cwd, command: launched.append(command),
    )

    task = run_task_from_spec(
        spec_path=spec_path,
        db_path=tmp_path / "tasks.db",
        agent_provider="codex",
        agent_model="gpt-5",
    )
    assert task.state == TaskState.CODING
    assert launched == ["codex --model gpt-5"]
    assert task.spec.agent == "codex"
    assert task.spec.agent_model == "gpt-5"


def test_run_task_from_spec_rejects_invalid_agent_override(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-invalid-override.json",
        {
            "task_id": "task_invalid_override",
            "project_name": "demo",
            "feature": "feat_invalid_override",
            "agent_cmd": "echo from-spec",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    with pytest.raises(AgvvError, match="Unsupported agent provider"):
        run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db", agent_provider="not-real")


def test_retry_task_relaunches_when_session_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_retry",
        project_name="demo",
        feature="feat_retry",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        session="sess-retry",
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.FAILED, last_error="boom", finished_at="2026-03-03T00:00:00+00:00")
    (tmp_path / "demo" / "feat_retry").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists", lambda _session: False)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature", lambda **kwargs: None)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session", lambda _s, _c, _m: None)

    retried = retry_task(task_id="task_retry", db_path=tmp_path / "tasks.db")
    assert retried.state == TaskState.CODING
    assert retried.last_error is None
    assert retried.finished_at is None


def test_retry_task_rejects_non_recoverable_state(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_non_retryable",
        project_name="demo",
        feature="feat_non_retryable",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.PR_MERGED, finished_at="2026-03-03T01:00:00+00:00")
    with pytest.raises(AgvvError, match="Cannot retry task in state: pr_merged"):
        retry_task(task_id="task_non_retryable", db_path=tmp_path / "tasks.db")


def test_cleanup_task_marks_cleaned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_clean",
        project_name="demo",
        feature="feat_clean",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    store.create_task(spec)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists", lambda _session: False)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.cleanup_feature",
        lambda project_name, feature, base_dir, delete_branch: None,
    )
    cleaned = cleanup_task("task_clean", db_path=tmp_path / "tasks.db")
    assert cleaned.state == TaskState.CLEANED


@pytest.mark.parametrize(("keep_branch", "expect_branch_delete"), [(True, False), (False, True)])
def test_cleanup_force_respects_keep_branch_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, keep_branch: bool, expect_branch_delete: bool
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id=f"task_force_{int(keep_branch)}",
        project_name="demo",
        feature=f"feat_force_{int(keep_branch)}",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        keep_branch_on_cleanup=keep_branch,
    )
    created = store.create_task(spec)
    task = store.get_task(created.id)
    paths = layout_paths(task.project_name, task.spec.base_dir, feature=task.feature)
    paths.repo_dir.mkdir(parents=True, exist_ok=True)
    if paths.feature_dir is not None:
        paths.feature_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, bool] = {}

    def _fake_cleanup_force(project_name: str, feature: str, base_dir: Path, delete_branch: bool) -> None:
        captured["delete_branch"] = delete_branch

    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists", lambda _session: False)
    monkeypatch.setattr("agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.cleanup_feature_force", _fake_cleanup_force)

    cleaned = cleanup_task(task.id, db_path=tmp_path / "tasks.db", force=True)
    assert cleaned.state == TaskState.CLEANED
    assert captured["delete_branch"] is expect_branch_delete


def test_list_task_statuses_filters_state(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_list",
        project_name="demo",
        feature="feat_list",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.CLEANED, finished_at=created.created_at)
    only_cleaned = list_task_statuses(tmp_path / "tasks.db", state=TaskState.CLEANED)
    assert len(only_cleaned) == 1
    assert only_cleaned[0].id == "task_list"
