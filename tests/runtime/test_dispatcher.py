"""Dispatcher and daemon runtime behavior tests."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

import pytest

from agvv.runtime import daemon_run_loop, daemon_run_once, reconcile_task
from agvv.runtime.models import TaskSpec, TaskState
from agvv.runtime.store import TaskStore
from agvv.shared.errors import AgvvError


def test_daemon_run_once_marks_running_done_when_session_ends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_done",
        project_name="demo",
        feature="feat_done",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.RUNNING, started_at=created.created_at)

    monkeypatch.setattr("agvv.orchestration.tmux_session_exists", lambda _session: False)

    results = daemon_run_once(tmp_path / "tasks.db")
    assert len(results) == 1
    updated = store.get_task("task_done")
    assert updated.state == TaskState.DONE


def test_daemon_run_once_rejects_non_positive_max_workers(tmp_path: Path) -> None:
    with pytest.raises(AgvvError, match="max_workers must be > 0"):
        daemon_run_once(tmp_path / "tasks.db", max_workers=0)


def test_daemon_run_once_skips_task_when_reconcile_lock_held(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_locked",
        project_name="demo",
        feature="feat_locked",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    assert store.try_acquire_reconcile_lock(created.id, owner_id="external-owner")

    monkeypatch.setattr(
        "agvv.runtime.dispatcher._STATE_HANDLERS",
        {TaskState.PENDING: lambda _store, _task: (_ for _ in ()).throw(RuntimeError("should not run"))},
    )

    results = daemon_run_once(tmp_path / "tasks.db")
    assert len(results) == 1
    assert store.get_task(created.id).state == TaskState.PENDING


def test_daemon_run_once_marks_failed_on_unexpected_handler_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_handler_error",
        project_name="demo",
        feature="feat_handler_error",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    store.create_task(spec)

    def _boom(_store: TaskStore, _task):
        raise RuntimeError("boom")

    monkeypatch.setattr("agvv.runtime.dispatcher._STATE_HANDLERS", {TaskState.PENDING: _boom})
    results = daemon_run_once(tmp_path / "tasks.db")
    assert len(results) == 1
    failed = store.get_task("task_handler_error")
    assert failed.state == TaskState.FAILED
    assert "Unexpected reconcile failure" in (failed.last_error or "")


def test_daemon_run_loop_rejects_non_positive_interval(tmp_path: Path) -> None:
    with pytest.raises(AgvvError, match="interval_seconds must be > 0"):
        daemon_run_loop(tmp_path / "tasks.db", interval_seconds=0)


def test_daemon_run_loop_stops_at_max_loops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_calls = {"count": 0}
    sleep_calls: list[int] = []

    def _fake_daemon_once(db_path=None, *, max_workers=1):
        run_calls["count"] += 1
        return []

    monkeypatch.setattr("agvv.runtime.dispatcher.daemon_run_once", _fake_daemon_once)
    monkeypatch.setattr("agvv.runtime.dispatcher.time.sleep", lambda seconds: sleep_calls.append(seconds))

    loops = daemon_run_loop(tmp_path / "tasks.db", interval_seconds=5, max_loops=3)
    assert loops == 3
    assert run_calls["count"] == 3
    assert sleep_calls == [5, 5]


def test_daemon_run_once_uses_parallel_path_when_multiple_workers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    for task_id in ("parallel_a", "parallel_b"):
        spec = TaskSpec(
            task_id=task_id,
            project_name="demo",
            feature=f"feat_{task_id}",
            agent_cmd="echo run",
            base_dir=tmp_path,
            requirements="do something",
        )
        store.create_task(spec)

    submitted: list[str] = []
    observed_max_workers: list[int] = []

    class _FakeExecutor:
        def __init__(self, *, max_workers: int):
            observed_max_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, task_id, store_obj, *, lock_owner):
            submitted.append(task_id)
            future: Future = Future()
            future.set_result(fn(task_id, store_obj, lock_owner=lock_owner))
            return future

    monkeypatch.setattr("agvv.runtime.dispatcher._STATE_HANDLERS", {})
    monkeypatch.setattr("agvv.runtime.dispatcher.ThreadPoolExecutor", _FakeExecutor)
    monkeypatch.setattr("agvv.runtime.dispatcher.as_completed", lambda futures: list(futures))

    results = daemon_run_once(tmp_path / "tasks.db", max_workers=2)
    assert observed_max_workers == [2]
    assert sorted(submitted) == ["parallel_a", "parallel_b"]
    assert sorted(item.id for item in results) == ["parallel_a", "parallel_b"]


def test_reconcile_task_returns_terminal_state_unchanged(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="task_terminal",
        project_name="demo",
        feature="feat_terminal",
        agent_cmd="echo run",
        base_dir=tmp_path,
        requirements="do something",
    )
    created = store.create_task(spec)
    store.update_task(created.id, state=TaskState.CLEANED)
    task = reconcile_task("task_terminal", tmp_path / "tasks.db")
    assert task.state == TaskState.CLEANED
