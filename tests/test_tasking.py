from __future__ import annotations

import json
from pathlib import Path

import pytest

import agvv.tasking as tasking
from agvv.tasking import (
    AgvvError,
    TaskSpec,
    TaskState,
    TaskStore,
    cleanup_task,
    daemon_run_once,
    list_task_statuses,
    load_task_spec,
    retry_task,
    run_task_from_spec,
)


def _write_spec(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_task_spec_json_success(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task.json",
        {
            "task_id": "task_1",
            "project_name": "demo",
            "feature": "feat_1",
            "agent_cmd": "echo build",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.task_id == "task_1"
    assert spec.base_dir == tmp_path.resolve()
    assert spec.timeout_minutes == 240


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
    calls: list[str] = []

    def _fake_start_feature(**kwargs):
        feature_dir = Path(kwargs["base_dir"]) / kwargs["project_name"] / kwargs["feature"]
        feature_dir.mkdir(parents=True, exist_ok=True)
        return None

    monkeypatch.setattr("agvv.tasking.start_feature", _fake_start_feature)
    monkeypatch.setattr("agvv.tasking.tmux_session_exists", lambda session: False)
    monkeypatch.setattr(
        "agvv.tasking.tmux_new_session",
        lambda session, cwd, command: calls.append(f"{session}:{cwd}:{command}"),
    )

    task = run_task_from_spec(spec_path=spec_path, db_path=tmp_path / "tasks.db")
    assert task.state == TaskState.CODING
    assert calls


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
    store.update_task(
        created.id,
        state=TaskState.FAILED,
        last_error="boom",
        finished_at="2026-03-03T00:00:00+00:00",
    )

    feature_dir = tmp_path / "demo" / "feat_retry"
    feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.tasking.tmux_session_exists", lambda session: False)
    monkeypatch.setattr("agvv.tasking.start_feature", lambda **kwargs: None)
    monkeypatch.setattr("agvv.tasking.tmux_new_session", lambda session, cwd, command: None)

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

    after = store.get_task("task_non_retryable")
    assert after.state == TaskState.PR_MERGED


def test_daemon_run_once_promotes_coding_to_pr_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_daemon",
        project_name="demo",
        feature="feat_daemon",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.CODING, started_at=created.created_at)

    feature_dir = tmp_path / "demo" / "feat_daemon"
    feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("agvv.tasking.tmux_session_exists", lambda session: False)
    monkeypatch.setattr("agvv.tasking._commit_and_push", lambda task, worktree: None)
    monkeypatch.setattr("agvv.tasking._ensure_pr_number", lambda task, worktree: 42)

    results = daemon_run_once(tmp_path / "tasks.db")
    assert len(results) == 1

    updated = store.get_task("task_daemon")
    assert updated.state == TaskState.PR_OPEN
    assert updated.pr_number == 42


def test_daemon_run_once_relaunches_on_needs_work(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_review",
        project_name="demo",
        feature="feat_review",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        max_retry_cycles=2,
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=11, started_at=created.created_at)

    feature_dir = tmp_path / "demo" / "feat_review"
    feature_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "agvv.tasking.check_pr_status",
        lambda repo, pr_number: type(
            "R",
            (),
            {"status": "needs_work", "reason": "changes_requested", "state": "OPEN", "review_decision": "CHANGES_REQUESTED"},
        )(),
    )
    monkeypatch.setattr(
        "agvv.tasking.summarize_pr_feedback",
        lambda repo, pr_number: type(
            "S",
            (),
            {"actionable": ["Actionable comments posted: 1"], "skipped": ["Skipped informational bot comment"]},
        )(),
    )
    monkeypatch.setattr("agvv.tasking.tmux_session_exists", lambda session: False)
    monkeypatch.setattr("agvv.tasking.tmux_new_session", lambda session, cwd, command: None)

    daemon_run_once(tmp_path / "tasks.db")
    updated = store.get_task("task_review")
    assert updated.state == TaskState.CODING
    assert updated.repair_cycles == 1
    assert (feature_dir / ".agvv" / "feedback.txt").exists()


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

    monkeypatch.setattr("agvv.tasking.tmux_session_exists", lambda session: False)
    monkeypatch.setattr("agvv.tasking.cleanup_feature", lambda project_name, feature, base_dir, delete_branch: None)

    cleaned = cleanup_task("task_clean", db_path=tmp_path / "tasks.db")
    assert cleaned.state == TaskState.CLEANED


@pytest.mark.parametrize(
    ("keep_branch", "expect_branch_delete"),
    [
        (True, False),
        (False, True),
    ],
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

    paths = tasking.layout_paths(task.project_name, task.spec.base_dir, feature=task.feature)
    paths.repo_dir.mkdir(parents=True, exist_ok=True)
    if paths.feature_dir is not None:
        paths.feature_dir.mkdir(parents=True, exist_ok=True)

    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], cwd: Path | None = None):
        calls.append(cmd)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.tasking._run_command", _fake_run_command)
    monkeypatch.setattr(
        "agvv.tasking.subprocess.run",
        lambda *args, **kwargs: type("R", (), {"returncode": 0})(),
    )

    tasking._cleanup_force(task)

    branch_delete_calls = [cmd for cmd in calls if "branch" in cmd and "-D" in cmd]
    if expect_branch_delete:
        assert branch_delete_calls
    else:
        assert not branch_delete_calls


def test_ensure_pr_number_falls_back_when_create_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_pr_fallback",
        project_name="demo",
        feature="feat_pr_fallback",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    task = store.get_task(created.id)
    worktree = tmp_path / "demo" / "feat_pr_fallback"
    worktree.mkdir(parents=True, exist_ok=True)

    def _fake_run_command(cmd: list[str], cwd: Path | None = None):
        if cmd[:4] == ["gh", "pr", "create", "--repo"]:
            raise AgvvError("Command failed: gh pr create ... already exists")
        if cmd[:4] == ["gh", "pr", "list", "--repo"]:
            return type("R", (), {"stdout": "123\n"})()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("agvv.tasking._run_command", _fake_run_command)

    pr_number = tasking._ensure_pr_number(task, worktree)
    assert pr_number == 123


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
