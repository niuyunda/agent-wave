"""Orchestration adapter: injectable wrapper for testability.

All runtime modules reference ``DEFAULT_ORCHESTRATION_PORT`` rather than
importing ``agvv.orchestration`` directly, so tests can monkeypatch individual
methods without replacing the entire module.
"""

from __future__ import annotations

from pathlib import Path

import agvv.orchestration as _orch
from agvv.orchestration.executor import CommandRunner
from agvv.orchestration.models import LayoutPaths, PrCheckResult, PrFeedbackSummary


class OrchestrationPort:
    """Thin delegating wrapper around the orchestration package."""

    def layout_paths(
        self,
        project_name: str,
        base_dir: Path,
        feature: str | None = None,
    ) -> LayoutPaths:
        """Return canonical layout paths for a project (and optional feature worktree).

        Args:
            project_name: Short identifier for the project.
            base_dir: Root directory that contains all project state.
            feature: Optional feature branch name; if given, ``feature_dir`` is populated.

        Returns:
            A ``LayoutPaths`` object with ``repo_dir``, ``main_dir``, and optionally
            ``feature_dir`` attributes.
        """
        return _orch.layout_paths(project_name, base_dir, feature)

    def init_project(self, project_name: str, base_dir: Path) -> LayoutPaths:
        """Initialise a bare project repository under ``base_dir``.

        Args:
            project_name: Short identifier for the project.
            base_dir: Root directory in which the project is created.

        Returns:
            ``LayoutPaths`` with the newly initialised paths.
        """
        return _orch.init_project(project_name, base_dir)

    def adopt_project(
        self,
        existing_repo: Path,
        project_name: str,
        base_dir: Path,
    ) -> tuple[LayoutPaths, str]:
        """Clone an existing local repository into the managed project layout.

        Args:
            existing_repo: Path to the existing git repository to adopt.
            project_name: Short identifier for the project.
            base_dir: Root directory in which the managed structure is created.

        Returns:
            Tuple of ``(LayoutPaths, default_branch_name)``.
        """
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
        """Create a git worktree for a new feature branch and write task context.

        Args:
            project_name: Short identifier for the project.
            feature: Feature branch / worktree name (must not contain spaces).
            base_dir: Root directory that contains all project state.
            from_branch: Base branch to branch off (e.g. ``"main"``).
            agent: Agent provider identifier written to the worktree context.
            task_id: Task identifier written to the worktree context.
            ticket: Optional ticket reference written to the worktree context.
            params: Arbitrary key/value pairs injected into the worktree context.
            create_dirs: Sub-directories to pre-create inside the worktree.

        Returns:
            ``LayoutPaths`` including the new ``feature_dir``.
        """
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
        """Remove the feature worktree and optionally delete the branch.

        Args:
            project_name: Short identifier for the project.
            feature: Feature branch / worktree name.
            base_dir: Root directory that contains all project state.
            delete_branch: If ``True``, delete the feature branch after removing
                the worktree.
        """
        _orch.cleanup_feature(project_name, feature, base_dir, delete_branch)

    def cleanup_feature_force(
        self,
        project_name: str,
        feature: str,
        base_dir: Path,
        delete_branch: bool,
    ) -> None:
        """Force-remove the feature worktree, discarding uncommitted changes.

        Args:
            project_name: Short identifier for the project.
            feature: Feature branch / worktree name.
            base_dir: Root directory that contains all project state.
            delete_branch: If ``True``, delete the feature branch after removal.
        """
        _orch.cleanup_feature_force(project_name, feature, base_dir, delete_branch)

    def tmux_session_exists(self, session: str) -> bool:
        """Return whether a tmux session with this name is currently running.

        Args:
            session: tmux session name.
        """
        return _orch.tmux_session_exists(session)

    def tmux_kill_session(self, session: str) -> None:
        """Kill a running tmux session.

        Args:
            session: tmux session name to kill.
        """
        _orch.tmux_kill_session(session)

    def tmux_new_session(self, session: str, cwd: Path, command: str) -> None:
        """Create a new detached tmux session running ``command``.

        Args:
            session: Name for the new session.
            cwd: Working directory for the session.
            command: Shell command to run inside the session.
        """
        _orch.tmux_new_session(session, cwd, command)

    def tmux_pipe_pane(self, session: str, output_path: Path) -> None:
        """Pipe tmux pane output to a file for continuous log capture.

        Args:
            session: tmux session name.
            output_path: Destination file path for captured output.
        """
        _orch.tmux_pipe_pane(session, output_path)

    def commit_and_push_branch(
        self,
        *,
        worktree: Path,
        feature: str,
        base_branch: str,
        remote: str,
        commit_message: str,
        run_git_cmd: CommandRunner | None = None,
    ) -> None:
        """Commit pending changes in the worktree and push the feature branch.

        Args:
            worktree: Path to the git worktree.
            feature: Feature branch name to push.
            base_branch: Base branch (used to verify commits exist ahead of it).
            remote: Git remote name to push to.
            commit_message: Commit message for any staged changes.
            run_git_cmd: Optional command-runner override for testing.
        """
        _orch.commit_and_push_branch(
            worktree=worktree,
            feature=feature,
            base_branch=base_branch,
            remote=remote,
            commit_message=commit_message,
            run_git_cmd=run_git_cmd,
        )

    def git_remote_exists(
        self,
        *,
        worktree: Path,
        remote: str,
        run_git_cmd: CommandRunner | None = None,
    ) -> bool:
        """Return whether a git remote is configured in the worktree's repository.

        Args:
            worktree: Path to the git worktree.
            remote: Remote name to check (e.g. ``"origin"``).
            run_git_cmd: Optional command-runner override for testing.
        """
        return _orch.git_remote_exists(
            worktree=worktree,
            remote=remote,
            run_git_cmd=run_git_cmd,
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
        """Create or look up an open PR and return its number.

        Args:
            repo: GitHub ``owner/repo`` slug.
            feature: Feature branch name used as head ref.
            pr_base: Target base branch for the pull request.
            title: PR title used when creating a new PR.
            body: PR body used when creating a new PR.
            worktree: Path to the feature worktree (needed by ``gh``).
            pr_number: If non-``None``, that number is returned directly (no-op).

        Returns:
            The PR number (int).
        """
        return _orch.ensure_pr_number_for_branch(
            repo=repo,
            feature=feature,
            pr_base=pr_base,
            title=title,
            body=body,
            worktree=worktree,
            pr_number=pr_number,
        )

    def check_pr_status(self, repo: str, pr_number: int) -> PrCheckResult:
        """Fetch the current status of a PR via the GitHub CLI.

        Args:
            repo: GitHub ``owner/repo`` slug.
            pr_number: PR number to check.

        Returns:
            A ``PrCheckResult`` with ``status``, ``state``, and ``review_decision``.
        """
        return _orch.check_pr_status(repo, pr_number)

    def summarize_pr_feedback(self, repo: str, pr_number: int) -> PrFeedbackSummary:
        """Summarise PR review comments into actionable and skipped buckets.

        Args:
            repo: GitHub ``owner/repo`` slug.
            pr_number: PR number to summarise.

        Returns:
            A ``PrFeedbackSummary`` with ``actionable`` and ``skipped`` lists.
        """
        return _orch.summarize_pr_feedback(repo, pr_number)

    def write_pr_feedback_file(
        self,
        *,
        worktree: Path,
        task_id: str,
        pr_number: int,
        feedback: PrFeedbackSummary,
    ) -> Path:
        """Write a PR feedback summary file into the feature worktree.

        Args:
            worktree: Path to the feature worktree.
            task_id: Task identifier, embedded in the feedback header.
            pr_number: PR number, embedded in the feedback header.
            feedback: Summarised feedback to persist.

        Returns:
            Path to the written ``feedback.txt`` file.
        """
        return _orch.write_pr_feedback_file(
            worktree=worktree,
            task_id=task_id,
            pr_number=pr_number,
            feedback=feedback,
        )


DEFAULT_ORCHESTRATION_PORT: OrchestrationPort = OrchestrationPort()
