"""Data models for agvv."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    failed = "failed"
    blocked = "blocked"
    done = "done"


class RunPurpose(str, Enum):
    implement = "implement"
    test = "test"
    review = "review"
    repair = "repair"


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    stalled = "stalled"
    stopped = "stopped"


class TaskMeta(BaseModel):
    """Canonical front-matter fields agvv reads/writes in task.md.

    On disk, ``task.md`` may include additional YAML keys; those are preserved
    when the task is created via ``task add`` and remain visible to
    ``task list`` / ``task show``.
    """

    name: str
    status: TaskStatus = TaskStatus.pending
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))


class RunMeta(BaseModel):
    """Front-matter fields for a run record."""

    purpose: RunPurpose
    agent: str
    status: RunStatus = RunStatus.running
    started_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    finished_at: Optional[str] = None
    checkpoint: Optional[str] = None
    pid: Optional[int] = None
    launcher_pid: Optional[int] = None
    pgid: Optional[int] = None
    exit_code: Optional[int] = None
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    base_branch: Optional[str] = None
    base_commit: Optional[str] = None
    report_path: Optional[str] = None


class ProjectEntry(BaseModel):
    """An entry in the global projects registry."""

    path: str
