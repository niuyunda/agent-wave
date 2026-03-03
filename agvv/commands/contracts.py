"""Typed command-layer contracts used by CLI adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agvv.orchestration.models import LayoutPaths
from agvv.runtime.models import TaskState
from agvv.runtime.store import TaskSnapshot


class RunTaskFromSpecFn(Protocol):
    """Typed callable for creating and launching a task from spec."""

    def __call__(
        self,
        spec_path: Path,
        db_path: Path | None = None,
        *,
        agent_provider: str | None = None,
        agent_model: str | None = None,
    ) -> TaskSnapshot:
        """Create a task from a spec file and launch its coding session."""


class ListTaskStatusesFn(Protocol):
    """Typed callable for querying task snapshots."""

    def __call__(self, db_path: Path | None = None, state: TaskState | None = None) -> list[TaskSnapshot]:
        """List task snapshots, optionally filtered by state."""


class RetryTaskFn(Protocol):
    """Typed callable for retrying one task."""

    def __call__(self, task_id: str, db_path: Path | None = None, session: str | None = None) -> TaskSnapshot:
        """Retry a single task and optionally override the tmux session."""


class CleanupTaskFn(Protocol):
    """Typed callable for cleaning up one task."""

    def __call__(self, task_id: str, db_path: Path | None = None, force: bool = False) -> TaskSnapshot:
        """Clean up resources associated with one task."""


class DaemonRunOnceFn(Protocol):
    """Typed callable for running one daemon reconcile pass."""

    def __call__(self, db_path: Path | None = None, *, max_workers: int = 1) -> list[TaskSnapshot]:
        """Reconcile active tasks once and return updated snapshots."""


class DaemonRunLoopFn(Protocol):
    """Typed callable for running daemon loop mode."""

    def __call__(
        self,
        db_path: Path | None = None,
        interval_seconds: int = 30,
        max_loops: int | None = None,
        *,
        max_workers: int = 1,
    ) -> int:
        """Run repeated reconcile loops and return number of completed iterations."""


class InitProjectFn(Protocol):
    """Typed callable for initializing a project layout."""

    def __call__(self, project_name: str, base_dir: Path) -> LayoutPaths:
        """Initialize a project and return resolved layout paths."""


class AdoptProjectFn(Protocol):
    """Typed callable for adopting an existing repository."""

    def __call__(self, existing_repo: Path, project_name: str, base_dir: Path) -> tuple[LayoutPaths, str]:
        """Adopt an existing repo and return layout paths and chosen base branch."""
