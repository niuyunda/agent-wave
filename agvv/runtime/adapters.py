"""Default runtime adapters for orchestration ports."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import agvv.orchestration as orchestration
from agvv.orchestration.models import PrFeedbackSummary
from agvv.runtime.ports import LayoutPathsView, OrchestrationPort, PrCheckResultView, PrFeedbackSummaryView


class DefaultOrchestrationPort:
    """Port adapter that delegates runtime requests to orchestration API."""

    def init_project(self, project_name: str, base_dir: Path) -> LayoutPathsView:
        """Initialize managed project layout for a new project."""
        return orchestration.init_project(project_name, base_dir)

    def adopt_project(self, existing_repo: Path, project_name: str, base_dir: Path) -> tuple[LayoutPathsView, str]:
        """Adopt an existing repository into the managed project layout."""
        return orchestration.adopt_project(existing_repo, project_name, base_dir)

    def layout_paths(self, project_name: str, base_dir: Path, *, feature: str | None = None) -> LayoutPathsView:
        """Return computed project layout paths for runtime operations."""
        return orchestration.layout_paths(project_name, base_dir, feature=feature)

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
    ) -> LayoutPathsView:
        """Initialize feature workspace and return resulting layout paths."""
        return orchestration.start_feature(
            project_name=project_name,
            feature=feature,
            base_dir=base_dir,
            from_branch=from_branch,
            agent=agent,
            task_id=task_id,
            ticket=ticket,
            params=params,
            create_dirs=create_dirs,
        )

    def cleanup_feature(self, project_name: str, feature: str, base_dir: Path, delete_branch: bool) -> LayoutPathsView:
        """Cleanup feature resources in standard mode."""
        return orchestration.cleanup_feature(project_name, feature, base_dir, delete_branch=delete_branch)

    def cleanup_feature_force(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> LayoutPathsView:
        """Cleanup feature resources even if normal cleanup fails."""
        return orchestration.cleanup_feature_force(project_name, feature, base_dir, delete_branch=delete_branch)

    def tmux_session_exists(self, session: str) -> bool:
        """Check whether a tmux session currently exists."""
        return orchestration.tmux_session_exists(session)

    def tmux_kill_session(self, session: str) -> None:
        """Terminate a tmux session by name."""
        orchestration.tmux_kill_session(session)

    def tmux_new_session(self, session: str, cwd: Path, command: str) -> None:
        """Create a detached tmux session and run a command."""
        orchestration.tmux_new_session(session, cwd, command)

    def commit_and_push_branch(
        self,
        *,
        worktree: Path,
        feature: str,
        base_branch: str,
        remote: str,
        commit_message: str,
    ) -> None:
        """Commit branch changes and push feature branch to remote."""
        orchestration.commit_and_push_branch(
            worktree=worktree,
            feature=feature,
            base_branch=base_branch,
            remote=remote,
            commit_message=commit_message,
        )

    def git_remote_exists(self, *, worktree: Path, remote: str) -> bool:
        """Check whether a git remote exists in the target repository/worktree."""
        return orchestration.git_remote_exists(worktree=worktree, remote=remote)

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
    ) -> int:
        """Return existing PR number or create/update PR for the branch."""
        return orchestration.ensure_pr_number_for_branch(
            repo=repo,
            feature=feature,
            pr_base=pr_base,
            title=title,
            body=body,
            worktree=worktree,
            pr_number=pr_number,
        )

    def check_pr_status(self, repo: str, pr_number: int) -> PrCheckResultView:
        """Fetch merged/open/closed status for a PR."""
        return orchestration.check_pr_status(repo, pr_number)

    def summarize_pr_feedback(self, repo: str, pr_number: int) -> PrFeedbackSummaryView:
        """Collect actionable and skipped PR feedback comments."""
        return orchestration.summarize_pr_feedback(repo, pr_number)

    def write_pr_feedback_file(
        self,
        *,
        worktree: Path,
        task_id: str,
        pr_number: int,
        actionable: Sequence[str],
        skipped: Sequence[str],
    ) -> Path:
        """Persist PR feedback details to a task-scoped markdown file."""
        return orchestration.write_pr_feedback_file(
            worktree=worktree,
            task_id=task_id,
            pr_number=pr_number,
            feedback=PrFeedbackSummary(actionable=tuple(actionable), skipped=tuple(skipped)),
        )


DEFAULT_ORCHESTRATION_PORT: OrchestrationPort = DefaultOrchestrationPort()


def resolve_orchestration_port(port: OrchestrationPort | None = None) -> OrchestrationPort:
    """Resolve explicit orchestration port override or use default adapter."""

    return DEFAULT_ORCHESTRATION_PORT if port is None else port
