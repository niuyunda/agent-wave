"""PR lifecycle handler tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agvv.runtime.models import TaskSpec, TaskState
from agvv.runtime.pr_lifecycle import handle_coding_completion, handle_pr_cycle
from agvv.runtime.store import TaskStore
from agvv.shared.pr import PrStatus


def _write_default_dod_result(feature_dir: Path) -> None:
    (feature_dir / ".agvv").mkdir(parents=True, exist_ok=True)
    payload = {
        "criteria": [
            {
                "item": "Relevant tests/checks pass for changed scope.",
                "status": "pass",
                "evidence": "ok",
            },
            {
                "item": "Changed files and verification results are summarized.",
                "status": "pass",
                "evidence": "ok",
            },
        ]
    }
    (feature_dir / ".agvv" / "dod_result.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _create_pr_open_task(store: TaskStore, tmp_path: Path, task_id: str) -> None:
    spec = TaskSpec(
        task_id=task_id,
        project_name="demo",
        feature=f"feat_{task_id}",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        auto_cleanup=False,
        timeout_minutes=60,
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=11)


def test_handle_coding_completion_fails_when_worktree_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_missing_worktree",
        project_name="demo",
        feature="feat_missing_worktree",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    coding = store.update_task(created.id, state=TaskState.CODING)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    updated = handle_coding_completion(store, coding)
    assert updated.state == TaskState.FAILED
    assert "Worktree missing" in (updated.last_error or "")


def test_handle_coding_completion_fails_when_finalize_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_finalize_error",
        project_name="demo",
        feature="feat_finalize_error",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    coding = store.update_task(created.id, state=TaskState.CODING)
    feature_dir = tmp_path / "demo" / "feat_finalize_error"
    feature_dir.mkdir(parents=True, exist_ok=True)
    _write_default_dod_result(feature_dir)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.commit_and_push_branch",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("push failed")),
    )
    updated = handle_coding_completion(store, coding)
    assert updated.state == TaskState.FAILED
    assert "Finalize coding failed" in (updated.last_error or "")


def test_handle_coding_completion_surfaces_missing_remote_guidance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_missing_remote",
        project_name="demo",
        feature="feat_missing_remote",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    coding = store.update_task(created.id, state=TaskState.CODING)
    feature_dir = tmp_path / "demo" / "feat_missing_remote"
    feature_dir.mkdir(parents=True, exist_ok=True)
    _write_default_dod_result(feature_dir)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.commit_and_push_branch",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("No git remote 'origin' configured for worktree /tmp/demo.")
        ),
    )

    updated = handle_coding_completion(store, coding)
    assert updated.state == TaskState.FAILED
    assert "No git remote 'origin' configured" in (updated.last_error or "")


def test_handle_coding_completion_fails_when_dod_result_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_missing_dod",
        project_name="demo",
        feature="feat_missing_dod",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    coding = store.update_task(created.id, state=TaskState.CODING)
    (tmp_path / "demo" / "feat_missing_dod").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    updated = handle_coding_completion(store, coding)
    assert updated.state == TaskState.FAILED
    assert "DoD validation failed" in (updated.last_error or "")


def test_handle_coding_completion_marks_blocked_when_trust_prompt_detected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_blocked_prompt",
        project_name="demo",
        feature="feat_blocked_prompt",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    created = store.create_task(spec)
    coding = store.update_task(
        created.id, state=TaskState.CODING, started_at="2026-03-03T00:00:00+00:00"
    )
    feature_dir = tmp_path / "demo" / "feat_blocked_prompt"
    (feature_dir / ".agvv").mkdir(parents=True, exist_ok=True)
    (feature_dir / ".agvv" / "agent_output.log").write_text(
        "Do you trust the contents of this directory?\nPress enter to continue\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: True,
    )

    updated = handle_coding_completion(store, coding)
    assert updated.state == TaskState.BLOCKED
    assert "interactive prompt" in (updated.last_error or "")


def test_handle_coding_completion_marks_timed_out_and_kills_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_coding_timeout",
        project_name="demo",
        feature="feat_coding_timeout",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        timeout_minutes=1,
    )
    created = store.create_task(spec)
    coding = store.update_task(
        created.id, state=TaskState.CODING, started_at="2000-01-01T00:00:00+00:00"
    )
    feature_dir = tmp_path / "demo" / "feat_coding_timeout"
    (feature_dir / ".agvv").mkdir(parents=True, exist_ok=True)
    killed: dict[str, bool] = {"value": False}
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: True,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_kill_session",
        lambda _session: killed.__setitem__("value", True),
    )

    updated = handle_coding_completion(store, coding)
    assert killed["value"] is True
    assert updated.state == TaskState.TIMED_OUT
    assert updated.last_error == "coding_timeout"


def test_handle_pr_cycle_fails_when_pr_number_missing(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_no_pr_number",
        project_name="demo",
        feature="feat_no_pr_number",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        auto_cleanup=False,
    )
    created = store.create_task(spec)
    task = store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=None)
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.FAILED
    assert "PR number missing" in (updated.last_error or "")


def test_handle_pr_cycle_times_out_without_auto_cleanup(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_timeout",
        project_name="demo",
        feature="feat_timeout",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        timeout_minutes=1,
        auto_cleanup=False,
    )
    created = store.create_task(spec)
    task = store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=88)
    conn = sqlite3.connect(store.path)
    try:
        with conn:
            conn.execute(
                "UPDATE tasks SET created_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", task.id),
            )
    finally:
        conn.close()
    updated = handle_pr_cycle(
        store,
        store.get_task(task.id),
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.TIMED_OUT
    assert updated.last_error == "task_timeout"


def test_handle_pr_cycle_times_out_with_auto_cleanup(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_timeout_cleanup",
        project_name="demo",
        feature="feat_timeout_cleanup",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        timeout_minutes=1,
        auto_cleanup=True,
    )
    created = store.create_task(spec)
    task = store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=89)
    conn = sqlite3.connect(store.path)
    try:
        with conn:
            conn.execute(
                "UPDATE tasks SET created_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", task.id),
            )
    finally:
        conn.close()

    called = {"cleanup": False}

    def _cleanup(task_id: str, db_path: Path | None, force: bool):
        called["cleanup"] = True
        return store.update_task(task_id, state=TaskState.CLEANED)

    cleaned = handle_pr_cycle(store, store.get_task(task.id), cleanup_task_fn=_cleanup)
    assert called["cleanup"] is True
    assert cleaned.state == TaskState.CLEANED


def test_handle_pr_cycle_merges_and_auto_cleans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_done_cleanup",
        project_name="demo",
        feature="feat_done_cleanup",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        auto_cleanup=True,
    )
    created = store.create_task(spec)
    task = store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=90)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: type("R", (), {"status": PrStatus.DONE})(),
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.update_task(
            task_id, state=TaskState.CLEANED
        ),
    )
    assert updated.state == TaskState.CLEANED


def test_handle_pr_cycle_closes_without_auto_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_closed_no_cleanup",
        project_name="demo",
        feature="feat_closed_no_cleanup",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        auto_cleanup=False,
    )
    created = store.create_task(spec)
    task = store.update_task(created.id, state=TaskState.PR_OPEN, pr_number=91)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: type("R", (), {"status": PrStatus.CLOSED})(),
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.PR_CLOSED


def test_handle_pr_cycle_marks_failed_when_pr_check_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    _create_pr_open_task(store, tmp_path, "task_check_error")
    task = store.get_task("task_check_error")
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: (_ for _ in ()).throw(RuntimeError("gh unavailable")),
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.FAILED
    assert "PR status check failed" in (updated.last_error or "")


def test_handle_pr_cycle_marks_failed_at_max_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_retry_limit",
        project_name="demo",
        feature="feat_retry_limit",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
        max_retry_cycles=1,
    )
    created = store.create_task(spec)
    task = store.update_task(
        created.id, state=TaskState.PR_OPEN, pr_number=99, repair_cycles=1
    )
    (tmp_path / "demo" / "feat_retry_limit").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: type("R", (), {"status": PrStatus.NEEDS_WORK})(),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.summarize_pr_feedback",
        lambda _repo, _pr: type("S", (), {"actionable": ["fix 1"], "skipped": []})(),
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.FAILED
    assert "Reached max retry cycles" in (updated.last_error or "")


def test_handle_pr_cycle_reuses_existing_tmux_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    _create_pr_open_task(store, tmp_path, "task_session_reuse")
    task = store.get_task("task_session_reuse")
    feature_dir = tmp_path / "demo" / "feat_task_session_reuse"
    feature_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: type("R", (), {"status": PrStatus.NEEDS_WORK})(),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.summarize_pr_feedback",
        lambda _repo, _pr: type("S", (), {"actionable": ["fix 1"], "skipped": []})(),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.write_pr_feedback_file",
        lambda **kwargs: feature_dir / ".agvv" / "feedback.txt",
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: True,
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.CODING
    assert updated.repair_cycles == task.repair_cycles


def test_handle_pr_cycle_marks_failed_when_relaunch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    _create_pr_open_task(store, tmp_path, "task_relaunch_fail")
    task = store.get_task("task_relaunch_fail")
    feature_dir = tmp_path / "demo" / "feat_task_relaunch_fail"
    feature_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.check_pr_status",
        lambda _repo, _pr: type("R", (), {"status": PrStatus.NEEDS_WORK})(),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.summarize_pr_feedback",
        lambda _repo, _pr: type("S", (), {"actionable": ["fix 1"], "skipped": []})(),
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.write_pr_feedback_file",
        lambda **kwargs: feature_dir / ".agvv" / "feedback.txt",
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_session_exists",
        lambda _session: False,
    )
    monkeypatch.setattr(
        "agvv.runtime.adapters.DEFAULT_ORCHESTRATION_PORT.tmux_new_session",
        lambda _session, _cwd, _cmd: (_ for _ in ()).throw(RuntimeError("tmux failed")),
    )
    updated = handle_pr_cycle(
        store,
        task,
        cleanup_task_fn=lambda task_id, db_path, force: store.get_task(task_id),
    )
    assert updated.state == TaskState.FAILED
    assert "Failed to relaunch coding session" in (updated.last_error or "")
