"""Worktree lifecycle management (internal implementation detail)."""

from __future__ import annotations

from pathlib import Path

from agvv.core import config
from agvv.utils import git


def worktree_path(project_path: Path, task_name: str) -> Path:
    return project_path / "worktrees" / task_name


def ensure_worktree(project_path: Path, task_name: str) -> Path:
    """Create worktree for a task if it doesn't exist. Returns worktree path."""
    wt = worktree_path(project_path, task_name)
    if wt.exists():
        return wt

    branch = f"{config.BRANCH_PREFIX}{task_name}"
    wt.parent.mkdir(parents=True, exist_ok=True)

    # Validate path safety: resolved path must be under project
    resolved = wt.resolve()
    project_resolved = project_path.resolve()
    if not str(resolved).startswith(str(project_resolved)):
        raise ValueError(f"Path traversal detected: {wt}")

    git.create_worktree(project_path, wt, branch)
    return wt


def cleanup_worktree(project_path: Path, task_name: str) -> None:
    """Remove worktree for a task."""
    wt = worktree_path(project_path, task_name)
    if not wt.exists():
        return
    git.remove_worktree(project_path, wt)
