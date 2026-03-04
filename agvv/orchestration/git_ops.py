"""Git branch and push operations used by orchestration."""

from __future__ import annotations

from pathlib import Path

from agvv.orchestration.executor import CommandRunner, run_git
from agvv.shared.errors import AgvvError

_run_git: CommandRunner = run_git


def git_remote_exists(
    *,
    worktree: Path,
    remote: str,
    run_git_cmd: CommandRunner | None = None,
) -> bool:
    """Return whether a git remote is configured in the target repository."""

    runner = run_git_cmd or _run_git
    normalized_remote = (remote or "").strip()
    if not normalized_remote:
        return False
    try:
        runner(["remote", "get-url", normalized_remote], cwd=worktree)
    except AgvvError:
        return False
    return True


def _is_internal_status_line(line: str) -> bool:
    """Return whether a porcelain status line points to AGVV internal metadata."""

    raw = line.rstrip()
    if len(raw) < 4:
        return False
    path_field = raw[3:]
    # Rename lines look like "old -> new"; treat them as internal only if target is internal.
    if " -> " in path_field:
        path_field = path_field.split(" -> ", 1)[1]
    path = path_field.strip()
    return path == ".agvv" or path.startswith(".agvv/")


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
    normalized_remote = (remote or "").strip()
    if not normalized_remote:
        raise AgvvError("git remote name is required")

    if not git_remote_exists(worktree=worktree, remote=normalized_remote, run_git_cmd=runner):
        raise AgvvError(
            f"No git remote '{normalized_remote}' configured for worktree {worktree}. "
            f"Configure it with `git remote add {normalized_remote} <url>` "
            "or set `branch_remote` in task spec."
        )

    status_raw = runner(["status", "--porcelain"], cwd=worktree).stdout
    status_lines = [line for line in status_raw.splitlines() if line.strip()]
    has_non_internal_changes = any(not _is_internal_status_line(line) for line in status_lines)

    if has_non_internal_changes:
        normalized_message = (commit_message or "").strip()
        if not normalized_message:
            raise AgvvError("commit message is required")
        runner(["add", "-A", "--", ".", ":(exclude).agvv/**"], cwd=worktree)
        runner(["commit", "-m", normalized_message, "--", ".", ":(exclude).agvv/**"], cwd=worktree)

    ahead_raw = runner(["rev-list", "--count", f"{base_branch}..{feature}"], cwd=worktree).stdout.strip()
    if int(ahead_raw or "0") <= 0:
        raise AgvvError(f"Task produced no commits ahead of base branch '{base_branch}'.")

    runner(["push", "-u", normalized_remote, feature], cwd=worktree)
