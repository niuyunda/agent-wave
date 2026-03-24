"""Runtime state dispatcher: route tasks by current state."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from agvv.runtime.models import TERMINAL_STATES, TaskState
from agvv.runtime.session_lifecycle import launch_coding_session
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso, parse_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.orchestration import acp_ops
from agvv.shared.errors import AgvvError

_LOGGER = logging.getLogger(__name__)


def _session_timed_out(task: TaskSnapshot) -> bool:
    """Return whether the task session runtime exceeded the configured timeout."""
    since = parse_iso(task.started_at or task.created_at)
    elapsed = datetime.now(tz=timezone.utc) - since
    return elapsed > timedelta(minutes=task.spec.timeout_minutes)


def _handle_pending(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Launch a fresh coding session for pending tasks."""
    return launch_coding_session(store, task, fresh_setup=True)


def _handle_running(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Check whether the coding session is still alive; transition when it ends."""
    from agvv.runtime.models import acp_agent_subcommand

    worktree = feature_worktree_path(task)
    agent_subcmd = acp_agent_subcommand(task.agent or "codex")

    if _session_timed_out(task):
        message = (
            f"Coding session exceeded timeout ({task.spec.timeout_minutes} minutes)."
        )
        store.add_event(
            task.id,
            "error",
            "session.timeout",
            message,
            {"session": task.session, "timeout_minutes": task.spec.timeout_minutes},
        )
        try:
            acp_ops.acpx_close_session(agent_subcmd, task.session, worktree)
        except Exception as exc:
            store.add_event(
                task.id,
                "warning",
                "session.timeout.kill",
                f"Failed to close timed-out session: {exc}",
                {"session": task.session},
            )
        return store.update_task(
            task.id,
            state=TaskState.TIMED_OUT,
            last_error="session_timeout",
            finished_at=now_iso(),
        )

    if acp_ops.acpx_session_running(agent_subcmd, task.session, worktree):
        return task  # still running, nothing to do

    # Session ended — mark done
    store.add_event(
        task.id,
        "info",
        "session.done",
        "Coding session ended",
        {"session": task.session},
    )
    return store.update_task(
        task.id, state=TaskState.DONE, finished_at=now_iso(), last_error=None
    )


_STATE_HANDLERS = {
    TaskState.PENDING: _handle_pending,
    TaskState.RUNNING: _handle_running,
}


def _reconcile_task(task_id: str, store: TaskStore, *, lock_owner: str) -> TaskSnapshot:
    """Reconcile one task by dispatching to its current-state handler."""
    task = store.get_task(task_id)
    if task.state in TERMINAL_STATES:
        return task
    if not store.try_acquire_reconcile_lock(task_id, owner_id=lock_owner):
        return task
    try:
        task = store.get_task(task_id)
        if task.state in TERMINAL_STATES:
            return task
        handler = _STATE_HANDLERS.get(task.state)
        if handler is None:
            return task
        return handler(store, task)
    finally:
        store.release_reconcile_lock(task_id, owner_id=lock_owner)


def _reconcile_task_safe(
    task_id: str, store: TaskStore, *, lock_owner: str
) -> TaskSnapshot:
    """Reconcile one task and convert unexpected failures into FAILED state."""
    try:
        return _reconcile_task(task_id, store, lock_owner=lock_owner)
    except Exception as exc:
        _LOGGER.exception("Unexpected reconcile failure for task %s", task_id)
        task = store.get_task(task_id)
        return mark_failed(
            store, task, "daemon.reconcile", f"Unexpected reconcile failure: {exc}"
        )


def reconcile_task(task_id: str, db_path: Path | None = None) -> TaskSnapshot:
    """Reconcile one task by dispatching to its current-state handler."""
    store = TaskStore(db_path)
    return _reconcile_task_safe(task_id, store, lock_owner=f"reconcile-{uuid4()}")


def daemon_run_once(
    db_path: Path | None = None, *, max_workers: int = 1
) -> list[TaskSnapshot]:
    """Reconcile all active tasks once."""
    if max_workers <= 0:
        raise AgvvError("max_workers must be > 0")
    store = TaskStore(db_path)
    active = store.list_active_tasks()
    if not active:
        return []
    if max_workers == 1 or len(active) == 1:
        lock_owner = f"daemon-{uuid4()}"
        return [
            _reconcile_task_safe(task.id, store, lock_owner=lock_owner)
            for task in active
        ]

    indexed_tasks = list(enumerate(active))
    results: list[TaskSnapshot | None] = [None] * len(indexed_tasks)
    lock_owner = f"daemon-{uuid4()}"
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(indexed_tasks))
    ) as executor:
        future_to_index = {
            executor.submit(
                _reconcile_task_safe, task.id, store, lock_owner=lock_owner
            ): index
            for index, task in indexed_tasks
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()

    return [item for item in results if item is not None]


def daemon_run_loop(
    db_path: Path | None = None,
    interval_seconds: int = 30,
    max_loops: int | None = None,
    *,
    max_workers: int = 1,
) -> int:
    """Run reconcile loop until interrupted or reaching max_loops."""
    if interval_seconds <= 0:
        raise AgvvError("interval_seconds must be > 0")
    if max_loops is not None and max_loops < 0:
        raise AgvvError("max_loops must be >= 0")
    if max_loops == 0:
        return 0

    loops = 0
    while True:
        daemon_run_once(db_path, max_workers=max_workers)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return loops
        time.sleep(interval_seconds)
