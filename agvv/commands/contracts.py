"""Typed command-layer contracts used by CLI adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

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
    ) -> TaskSnapshot: ...


class ListTaskStatusesFn(Protocol):
    """Typed callable for querying task snapshots."""

    def __call__(self, db_path: Path | None = None, state: TaskState | None = None) -> list[TaskSnapshot]: ...


class RetryTaskFn(Protocol):
    """Typed callable for retrying one task."""

    def __call__(self, task_id: str, db_path: Path | None = None, session: str | None = None) -> TaskSnapshot: ...


class CleanupTaskFn(Protocol):
    """Typed callable for cleaning up one task."""

    def __call__(self, task_id: str, db_path: Path | None = None, force: bool = False) -> TaskSnapshot: ...


class DaemonRunOnceFn(Protocol):
    """Typed callable for running one daemon reconcile pass."""

    def __call__(self, db_path: Path | None = None, *, max_workers: int = 1) -> list[TaskSnapshot]: ...


class DaemonRunLoopFn(Protocol):
    """Typed callable for running daemon loop mode."""

    def __call__(
        self,
        db_path: Path | None = None,
        interval_seconds: int = 30,
        max_loops: int | None = None,
        *,
        max_workers: int = 1,
    ) -> int: ...
