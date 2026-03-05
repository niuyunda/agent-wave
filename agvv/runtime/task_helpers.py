"""Shared task helpers for runtime state handlers and use cases."""

from __future__ import annotations

from pathlib import Path

import agvv.orchestration as orch
from agvv.runtime.models import TaskState
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.shared.errors import AgvvError


def feature_worktree_path(task: TaskSnapshot) -> Path:
    """Resolve feature worktree path for one runtime task."""
    paths = orch.layout_paths(
        task.project_name, task.spec.base_dir, feature=task.feature
    )
    if paths.feature_dir is None:
        raise AgvvError("Internal error: feature_dir missing")
    return paths.feature_dir


def mark_failed(
    store: TaskStore, task: TaskSnapshot, step: str, message: str
) -> TaskSnapshot:
    """Record failure event and transition task into FAILED."""
    store.add_event(task.id, "error", step, message)
    return store.update_task(
        task.id, state=TaskState.FAILED, last_error=message, finished_at=now_iso()
    )
