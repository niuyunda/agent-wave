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
    if "task_doc" not in payload:
        task_doc_path = path.with_suffix(".md")
        task_doc_path.write_text(
            "# Task Doc\n\n- Implement required changes.\n", encoding="utf-8"
        )
        payload["task_doc"] = str(task_doc_path)
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


def test_run_task_from_spec_starts_coding_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
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
    repo_dir = tmp_path / "demo" / "repo.git"
    main_dir = tmp_path / "demo" / "main"
    repo_dir.mkdir(parents=True, exist_ok=True)
    main_dir.mkdir(parents=True, exist_ok=True)

    def _fake_start_feature(**kwargs):
        feature_dir = (
            Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        )
        feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        _fake_start_feature,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.git_remote_exists",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda session, cwd, command: launched.append(f"{session}:{cwd}:{command}"),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert task.state == TaskState.CODING
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

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        _fake_start_feature,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.git_remote_exists",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _session, _cwd, command: launched.append(command),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _session, output_log_path: piped.append(str(output_log_path)),
    )

    task = run_task_from_spec(
        spec_path=spec_path,
        db_path=tmp_path / "tasks.db",
        agent_provider="codex",
    )
    assert task.state == TaskState.CODING
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
        run_task_from_spec(
            spec_path=spec_path,
            db_path=tmp_path / "tasks.db",
            agent_provider="not-real",
        )


def test_run_task_from_spec_rejects_missing_task_doc(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-missing-task-doc.json"
    spec_path.write_text(
        json.dumps(
            {
                "project_name": "demo",
                "feature": "feat_missing_doc",
                "repo": "owner/repo",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="task_doc"):
        run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")


def test_run_task_from_spec_rejects_non_markdown_task_doc(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-bad-task-doc.json"
    spec_path.write_text(
        json.dumps(
            {
                "project_name": "demo",
                "feature": "feat_bad_doc",
                "repo": "owner/repo",
                "task_doc": "./task.txt",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="Markdown"):
        run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")


def test_run_task_from_spec_ignores_spec_base_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-ignore-base-dir.json",
        {
            "task_id": "task_ignore_base_dir",
            "project_name": "demo",
            "feature": "feat_ignore_base_dir",
            "agent_cmd": "echo run",
            "repo": "owner/repo",
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

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.init_project",
        _fake_init_project,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        _fake_start_feature,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert seen["base_dir"] == tmp_path.resolve()


def test_run_task_from_spec_auto_inits_project_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-auto-init.json",
        {
            "task_id": "task_auto_init",
            "project_name": "demo",
            "feature": "feat_auto_init",
            "agent_cmd": "echo from-spec",
            "repo": "owner/repo",
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

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.init_project",
        _fake_init_project,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        _fake_start_feature,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert started["init"] is True
    assert task.state == TaskState.CODING


def test_run_task_from_spec_auto_adopts_existing_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    spec_path = _write_spec(
        tmp_path / "task-auto-adopt.json",
        {
            "task_id": "task_auto_adopt",
            "project_name": "demo",
            "feature": "feat_auto_adopt",
            "agent_cmd": "echo from-spec",
            "repo": "owner/repo",
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

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.adopt_project",
        _fake_adopt_project,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        _fake_start_feature,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    task = run_task_from_spec(
        spec_path=spec_path, db_path=tmp_path / "tasks.db", project_dir=source_repo
    )
    assert adopted["called"] is True
    assert task.state == TaskState.CODING


def test_retry_task_relaunches_when_session_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    store.update_task(
        created.id,
        state=TaskState.FAILED,
        last_error="boom",
        finished_at="2026-03-03T00:00:00+00:00",
    )
    (tmp_path / "demo" / "feat_retry").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    retried = retry_task(task_id="task_retry", db_path=tmp_path / "tasks.db")
    assert retried.state == TaskState.CODING
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
        repo="owner/repo",
        base_dir=tmp_path,
        session="sess-force",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.CODING, started_at="2026-03-03T00:00:00+00:00"
    )
    (tmp_path / "demo" / "feat_retry_force").mkdir(parents=True, exist_ok=True)

    called: dict[str, bool] = {"killed": False}
    session_live: dict[str, bool] = {"value": True}
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: session_live["value"],
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_kill_session",
        lambda _session: (
            called.__setitem__("killed", True),
            session_live.__setitem__("value", False),
        ),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    retried = retry_task(
        task_id="task_retry_force", db_path=tmp_path / "tasks.db", force_restart=True
    )
    assert called["killed"] is True
    assert retried.state == TaskState.CODING
    assert retried.finished_at is None


def test_retry_task_force_restart_kills_session_for_blocked_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_retry_force_blocked",
        project_name="demo",
        feature="feat_retry_force_blocked",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        session="sess-force-blocked",
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.BLOCKED, last_error="blocked-by-prompt"
    )
    (tmp_path / "demo" / "feat_retry_force_blocked").mkdir(parents=True, exist_ok=True)

    called: dict[str, bool] = {"killed": False}
    session_live: dict[str, bool] = {"value": True}
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: session_live["value"],
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_kill_session",
        lambda _session: (
            called.__setitem__("killed", True),
            session_live.__setitem__("value", False),
        ),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.start_feature",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _s, _c, _m: None,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_pipe_pane",
        lambda _s, _p: None,
    )

    retried = retry_task(
        task_id="task_retry_force_blocked",
        db_path=tmp_path / "tasks.db",
        force_restart=True,
    )
    assert called["killed"] is True
    assert retried.state == TaskState.CODING
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
    store.update_task(
        created.id, state=TaskState.PR_MERGED, finished_at="2026-03-03T01:00:00+00:00"
    )
    with pytest.raises(AgvvError, match="Cannot retry task in state: pr_merged"):
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
        repo="owner/repo",
        base_dir=tmp_path,
    )
    store.create_task(spec)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.cleanup_feature",
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
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    store.update_task(
        created.id, state=TaskState.BLOCKED, last_error="blocked by prompt"
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.cleanup_feature",
        lambda project_name, feature, base_dir, delete_branch: None,
    )
    cleaned = cleanup_task("task_clean_error", db_path=tmp_path / "tasks.db")
    assert cleaned.state == TaskState.CLEANED
    assert cleaned.last_error == "blocked by prompt"


@pytest.mark.parametrize(
    ("keep_branch", "expect_branch_delete"), [(True, False), (False, True)]
)
def test_cleanup_force_respects_keep_branch_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    keep_branch: bool,
    expect_branch_delete: bool,
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

    def _fake_cleanup_force(
        project_name: str, feature: str, base_dir: Path, delete_branch: bool
    ) -> None:
        captured["delete_branch"] = delete_branch

    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.cleanup_feature_force",
        _fake_cleanup_force,
    )

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
    store.update_task(
        created.id, state=TaskState.CLEANED, finished_at=created.created_at
    )
    only_cleaned = list_task_statuses(tmp_path / "tasks.db", state=TaskState.CLEANED)
    assert len(only_cleaned) == 1
    assert only_cleaned[0].id == "task_list"
