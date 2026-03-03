"""Core data models for orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agvv.shared.pr import PrStatus


@dataclass(frozen=True)
class LayoutPaths:
    """Resolved filesystem paths for a project/worktree layout."""

    project_dir: Path
    repo_dir: Path
    main_dir: Path
    feature_dir: Path | None = None


@dataclass(frozen=True)
class PrCheckResult:
    """Simplified PR check result for short review cycles."""

    status: PrStatus
    reason: str
    state: str
    review_decision: str | None


@dataclass(frozen=True)
class PrWaitResult:
    """Result of polling a PR for status updates."""

    result: PrCheckResult
    attempts: int
    timed_out: bool


@dataclass(frozen=True)
class PrNextAction:
    """Suggested next action for a PR based on current status."""

    status: PrStatus
    action: str
    note: str


@dataclass(frozen=True)
class PrFeedbackSummary:
    """Condensed actionable/non-actionable feedback summary for a PR."""

    actionable: tuple[str, ...]
    skipped: tuple[str, ...]
