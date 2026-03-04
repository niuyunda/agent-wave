"""Task retry use case."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.adapters import resolve_orchestration_port
from agvv.runtime.models import RECOVERABLE_RETRY_STATES
from agvv.runtime.ports import OrchestrationPort
from agvv.runtime.session_lifecycle import launch_coding_session
from agvv.runtime.store import TaskSnapshot, TaskStore
from agvv.runtime.task_helpers import feature_worktree_path
from agvv.shared.errors import AgvvError


def retry_task(
    task_id: str,
    db_path: Path | None = None,
    session: str | None = None,
    *,
    force_restart: bool = False,
    orchestration_port: OrchestrationPort | None = None,
) -> TaskSnapshot:
    """Retry task from recoverable states and relaunch coding session."""

    port = resolve_orchestration_port(orchestration_port)

    store = TaskStore(db_path)
    task = store.get_task(task_id)

    if task.state not in RECOVERABLE_RETRY_STATES:
        raise AgvvError(f"Cannot retry task in state: {task.state.value}")
    session_exists = port.tmux_session_exists(task.session)
    if session_exists and not force_restart:
        raise AgvvError(f"Task is already running in session: {task.session}")
    if session_exists and force_restart:
        port.tmux_kill_session(task.session)
        store.add_event(
            task.id,
            "warning",
            "task.retry.force_restart",
            "Killed existing tmux session before retry relaunch.",
            {"session": task.session, "state": task.state.value},
        )

    if session and session != task.session:
        store.add_event(task.id, "info", "task.retry", "Session override requested", {"session": session})
        task = store.update_task_session(task.id, session)

    worktree = feature_worktree_path(task, orchestration_port=port)
    return launch_coding_session(
        store,
        task,
        fresh_setup=not worktree.exists(),
        orchestration_port=port,
    )
