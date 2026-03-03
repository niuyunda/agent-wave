"""Session and workspace lifecycle operations for runtime tasks."""

from __future__ import annotations

from agvv.runtime.adapters import resolve_orchestration_port
from agvv.runtime.models import TaskState
from agvv.runtime.ports import OrchestrationPort
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.shared.errors import AgvvError


def launch_coding_session(
    store: TaskStore,
    task: TaskSnapshot,
    *,
    fresh_setup: bool,
    orchestration_port: OrchestrationPort | None = None,
) -> TaskSnapshot:
    """Ensure feature worktree exists and launch tmux coding session."""

    port = resolve_orchestration_port(orchestration_port)

    try:
        if port.tmux_session_exists(task.session):
            raise AgvvError(f"tmux session already exists: {task.session}")
        if fresh_setup:
            port.start_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                from_branch=task.spec.from_branch,
                agent=task.agent,
                task_id=task.id,
                ticket=task.spec.ticket,
                params={
                    **(task.spec.params or {}),
                    "task_doc": str(task.spec.task_doc) if task.spec.task_doc else "",
                },
                create_dirs=task.spec.create_dirs or [],
            )

        worktree = feature_worktree_path(task, orchestration_port=port)
        if not worktree.exists():
            raise AgvvError(f"Feature worktree not found: {worktree}")
        port.tmux_new_session(task.session, worktree, task.spec.agent_cmd)
    except Exception as exc:
        return mark_failed(store, task, "task.launch", f"Failed to launch coding session: {exc}")

    store.add_event(task.id, "info", "task.launch", "Coding session started", {"session": task.session})
    return store.update_task(
        task.id,
        state=TaskState.CODING,
        started_at=(task.started_at or now_iso()),
        finished_at=None,
        last_error=None,
    )
