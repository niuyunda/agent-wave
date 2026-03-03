"""Default runtime adapters for orchestration ports."""

from __future__ import annotations

from pathlib import Path

import agvv.orchestration as orchestration
from agvv.orchestration.models import PrFeedbackSummary
from agvv.runtime.ports import LayoutPathsView, OrchestrationPort, PrCheckResultView, PrFeedbackSummaryView


class DefaultOrchestrationPort:
    """Port adapter that delegates runtime requests to orchestration API."""

    def layout_paths(self, project_name: str, base_dir: Path, *, feature: str | None = None) -> LayoutPathsView:
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
        return orchestration.cleanup_feature(project_name, feature, base_dir, delete_branch=delete_branch)

    def cleanup_feature_force(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> LayoutPathsView:
        return orchestration.cleanup_feature_force(project_name, feature, base_dir, delete_branch=delete_branch)

    def tmux_session_exists(self, session: str) -> bool:
        return orchestration.tmux_session_exists(session)

    def tmux_kill_session(self, session: str) -> None:
        orchestration.tmux_kill_session(session)

    def tmux_new_session(self, session: str, cwd: Path, command: str) -> None:
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
        orchestration.commit_and_push_branch(
            worktree=worktree,
            feature=feature,
            base_branch=base_branch,
            remote=remote,
            commit_message=commit_message,
        )

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
        return orchestration.check_pr_status(repo, pr_number)

    def summarize_pr_feedback(self, repo: str, pr_number: int) -> PrFeedbackSummaryView:
        return orchestration.summarize_pr_feedback(repo, pr_number)

    def write_pr_feedback_file(
        self,
        *,
        worktree: Path,
        task_id: str,
        pr_number: int,
        actionable: list[str],
        skipped: list[str],
    ) -> Path:
        return orchestration.write_pr_feedback_file(
            worktree=worktree,
            task_id=task_id,
            pr_number=pr_number,
            feedback=PrFeedbackSummary(actionable=actionable, skipped=skipped),
        )


DEFAULT_ORCHESTRATION_PORT: OrchestrationPort = DefaultOrchestrationPort()


def resolve_orchestration_port(port: OrchestrationPort | None = None) -> OrchestrationPort:
    """Resolve explicit orchestration port override or use default adapter."""

    return port or DEFAULT_ORCHESTRATION_PORT
