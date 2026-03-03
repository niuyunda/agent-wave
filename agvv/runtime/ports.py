"""Runtime-facing port protocols for cross-layer orchestration calls."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agvv.shared.pr import PrStatus


class LayoutPathsView(Protocol):
    """Minimal layout view consumed by runtime."""

    feature_dir: Path | None


class PrCheckResultView(Protocol):
    """Minimal PR status view consumed by runtime."""

    status: PrStatus


class PrFeedbackSummaryView(Protocol):
    """Minimal PR feedback summary consumed by runtime."""

    actionable: list[str]
    skipped: list[str]


class OrchestrationPort(Protocol):
    """Runtime boundary for orchestration operations."""

    def layout_paths(self, project_name: str, base_dir: Path, *, feature: str | None = None) -> LayoutPathsView: ...

    def start_feature(
        self,
        *,
        project_name: str,
        feature: str,
        base_dir: Path,
        from_branch: str,
        agent: str | None,
        task_id: str | None,
        ticket: str | None,
        params: dict[str, str],
        create_dirs: list[str],
    ) -> LayoutPathsView: ...

    def cleanup_feature(self, project_name: str, feature: str, base_dir: Path, delete_branch: bool) -> LayoutPathsView: ...

    def cleanup_feature_force(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> LayoutPathsView: ...

    def tmux_session_exists(self, session: str) -> bool: ...

    def tmux_kill_session(self, session: str) -> None: ...

    def tmux_new_session(self, session: str, cwd: Path, command: str) -> None: ...

    def commit_and_push_branch(
        self,
        *,
        worktree: Path,
        feature: str,
        base_branch: str,
        remote: str,
        commit_message: str,
    ) -> None: ...

    def ensure_pr_number_for_branch(
        self,
        *,
        repo: str,
        feature: str,
        pr_base: str,
        title: str,
        body: str,
        worktree: Path,
        pr_number: int | None = None,
    ) -> int: ...

    def check_pr_status(self, repo: str, pr_number: int) -> PrCheckResultView: ...

    def summarize_pr_feedback(self, repo: str, pr_number: int) -> PrFeedbackSummaryView: ...

    def write_pr_feedback_file(
        self,
        *,
        worktree: Path,
        task_id: str,
        pr_number: int,
        actionable: list[str],
        skipped: list[str],
    ) -> Path: ...
