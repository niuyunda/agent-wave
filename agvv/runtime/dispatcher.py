"""Runtime state dispatcher: route tasks by current state."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from uuid import uuid4

from agvv.runtime.models import TERMINAL_STATES, TaskState
from agvv.runtime.pr_lifecycle import handle_coding_completion, handle_pr_cycle
from agvv.runtime.session_lifecycle import launch_coding_session
from agvv.runtime.store import TaskSnapshot, TaskStore
from agvv.runtime.task_helpers import mark_failed
from agvv.runtime.core import cleanup_task
from agvv.shared.errors import AgvvError

StateHandler = Callable[[TaskStore, TaskSnapshot], TaskSnapshot]
_LOGGER = logging.getLogger(__name__)


def _handle_pending(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Launch a fresh coding session for pending tasks."""
    return launch_coding_session(store, task, fresh_setup=True)


def _handle_coding(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Evaluate coding-session completion and transition state if needed."""
    return handle_coding_completion(store, task)


def _handle_pr_open(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Run PR lifecycle checks and reconcile feedback or merge outcomes."""
    return handle_pr_cycle(store, task, cleanup_task_fn=cleanup_task)


_STATE_HANDLERS: dict[TaskState, StateHandler] = {
    TaskState.PENDING: _handle_pending,
    TaskState.CODING: _handle_coding,
    TaskState.PR_OPEN: _handle_pr_open,
}


def _reconcile_task(task_id: str, store: TaskStore, *, lock_owner: str) -> TaskSnapshot:
    """Reconcile one task by dispatching to current-state handler."""
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
    """Reconcile one task and convert unexpected failures into task failure state."""
    try:
        return _reconcile_task(task_id, store, lock_owner=lock_owner)
    except Exception as exc:
        _LOGGER.exception("Unexpected reconcile failure for task %s", task_id)
        task = store.get_task(task_id)
        return mark_failed(
            store, task, "daemon.reconcile", f"Unexpected reconcile failure: {exc}"
        )


def reconcile_task(
    task_id: str,
    db_path: Path | None = None,
) -> TaskSnapshot:
    """Reconcile one task by dispatching to current-state handler."""
    store = TaskStore(db_path)
    return _reconcile_task_safe(task_id, store, lock_owner=f"reconcile-{uuid4()}")


def daemon_run_once(
    db_path: Path | None = None,
    *,
    max_workers: int = 1,
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
