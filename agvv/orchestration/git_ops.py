"""Git branch and push operations used by orchestration."""

from __future__ import annotations

from pathlib import Path

from agvv.orchestration.executor import CommandRunner, run_git
from agvv.shared.errors import AgvvError

_run_git: CommandRunner = run_git


def commit_and_push_branch(
    *,
    worktree: Path,
    feature: str,
    base_branch: str,
    remote: str,
    commit_message: str,
    run_git_cmd: CommandRunner | None = None,
) -> None:
    """Commit pending changes for a branch and push it to remote."""

    runner = run_git_cmd or _run_git

    status = runner(["status", "--porcelain"], cwd=worktree).stdout.strip()
    if status:
        normalized_message = (commit_message or "").strip()
        if not normalized_message:
            raise AgvvError("commit message is required")
        runner(["add", "-A"], cwd=worktree)
        runner(["commit", "-m", normalized_message], cwd=worktree)

    ahead_raw = runner(["rev-list", "--count", f"{base_branch}..{feature}"], cwd=worktree).stdout.strip()
    if int(ahead_raw or "0") <= 0:
        raise AgvvError(f"Task produced no commits ahead of base branch '{base_branch}'.")

    runner(["push", "-u", remote, feature], cwd=worktree)
