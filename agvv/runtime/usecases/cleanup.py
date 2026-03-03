"""Task cleanup use case."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.adapters import resolve_orchestration_port
from agvv.runtime.models import TaskState
from agvv.runtime.ports import OrchestrationPort
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import mark_failed


def cleanup_task(
    task_id: str,
    db_path: Path | None = None,
    force: bool = False,
    *,
    orchestration_port: OrchestrationPort | None = None,
) -> TaskSnapshot:
    """Cleanup task resources and transition to ``CLEANED``."""

    port = resolve_orchestration_port(orchestration_port)

    store = TaskStore(db_path)
    task = store.get_task(task_id)

    try:
        if port.tmux_session_exists(task.session):
            port.tmux_kill_session(task.session)

        delete_branch = not task.spec.keep_branch_on_cleanup
        if force:
            port.cleanup_feature_force(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                delete_branch=delete_branch,
            )
        else:
            port.cleanup_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                delete_branch=delete_branch,
            )
    except Exception as exc:
        return mark_failed(store, task, "task.cleanup", f"Cleanup failed: {exc}")

    store.add_event(task.id, "info", "task.cleanup", "Task resources cleaned")
    return store.update_task(task.id, state=TaskState.CLEANED, finished_at=now_iso(), last_error=None)
