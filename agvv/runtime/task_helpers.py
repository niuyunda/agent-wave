"""Shared task helpers for runtime state handlers and use cases."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.adapters import resolve_orchestration_port
from agvv.runtime.models import TaskSpec, TaskState
from agvv.runtime.ports import OrchestrationPort
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso


def feature_worktree_path(task: TaskSnapshot, *, orchestration_port: OrchestrationPort | None = None) -> Path:
    """Resolve feature worktree path for one runtime task."""

    port = resolve_orchestration_port(orchestration_port)
    paths = port.layout_paths(task.project_name, task.spec.base_dir, feature=task.feature)
    if paths.feature_dir is None:
        raise RuntimeError("Internal error: feature_dir missing")
    return paths.feature_dir


def task_doc_text(spec: TaskSpec) -> str:
    """Resolve PR body text from explicit body or task document file."""

    if spec.pr_body:
        return spec.pr_body
    if spec.task_doc:
        try:
            return spec.task_doc.read_text(encoding="utf-8").strip()
        except OSError:
            return f"Task document: {spec.task_doc}"
    return f"Automated task: {spec.task_id}"


def mark_failed(store: TaskStore, task: TaskSnapshot, step: str, message: str) -> TaskSnapshot:
    """Record failure event and transition task into ``FAILED``."""

    store.add_event(task.id, "error", step, message)
    return store.update_task(task.id, state=TaskState.FAILED, last_error=message, finished_at=now_iso())
