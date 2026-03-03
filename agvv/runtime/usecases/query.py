"""Task query/list use cases."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.models import TaskState
from agvv.runtime.store import TaskSnapshot, TaskStore


def list_task_statuses(db_path: Path | None = None, state: TaskState | None = None) -> list[TaskSnapshot]:
    """List runtime tasks sorted by update time."""

    return TaskStore(db_path).list_tasks(state=state)
