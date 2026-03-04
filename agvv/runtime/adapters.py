"""Orchestration adapter: injectable wrapper for testability.

All runtime modules reference ``DEFAULT_ORCHESTRATION_PORT`` rather than
importing ``agvv.orchestration`` directly, so tests can monkeypatch individual
methods without replacing the entire module.
"""

from __future__ import annotations

from pathlib import Path

import agvv.orchestration as _orch
from agvv.orchestration.models import LayoutPaths, PrCheckResult, PrFeedbackSummary


class OrchestrationPort:
    """Thin delegating wrapper around the orchestration package."""

    def layout_paths(
        self,
        project_name: str,
        base_dir: Path,
        feature: str | None = None,
    ) -> LayoutPaths:
        return _orch.layout_paths(project_name, base_dir, feature)

    def init_project(self, project_name: str, base_dir: Path) -> LayoutPaths:
        return _orch.init_project(project_name, base_dir)

    def adopt_project(
        self,
        existing_repo: Path,
        project_name: str,
        base_dir: Path,
    ) -> tuple[LayoutPaths, str]:
        return _orch.adopt_project(existing_repo, project_name, base_dir)

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
        params: dict,
        create_dirs: list[str],
    ) -> LayoutPaths:
        return _orch.start_feature(
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

    def cleanup_feature(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> None:
        _orch.cleanup_feature(project_name, feature, base_dir, delete_branch)

    def cleanup_feature_force(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> None:
        _orch.cleanup_feature_force(project_name, feature, base_dir, delete_branch)

    def tmux_session_exists(self, session: str) -> bool:
        return _orch.tmux_session_exists(session)

    def tmux_kill_session(self, session: str) -> None:
        _orch.tmux_kill_session(session)

    def tmux_new_session(self, session: str, cwd: Path, command: str) -> None:
        _orch.tmux_new_session(session, cwd, command)

    def tmux_pipe_pane(self, session: str, output_path: Path) -> None:
        _orch.tmux_pipe_pane(session, output_path)

    def commit_and_push_branch(self, **kwargs) -> None:
        _orch.commit_and_push_branch(**kwargs)

    def git_remote_exists(self, **kwargs) -> bool:
        return _orch.git_remote_exists(**kwargs)

    def ensure_pr_number_for_branch(self, **kwargs) -> int:
        return _orch.ensure_pr_number_for_branch(**kwargs)

    def check_pr_status(self, repo: str, pr_number: int) -> PrCheckResult:
        return _orch.check_pr_status(repo, pr_number)

    def summarize_pr_feedback(self, repo: str, pr_number: int) -> PrFeedbackSummary:
        return _orch.summarize_pr_feedback(repo, pr_number)

    def write_pr_feedback_file(self, **kwargs) -> Path:
        return _orch.write_pr_feedback_file(**kwargs)


DEFAULT_ORCHESTRATION_PORT: OrchestrationPort = OrchestrationPort()
