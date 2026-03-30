"""Git operation utilities."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        output = (e.stderr or "").strip() or (e.stdout or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {output}") from e


def get_repo_root(path: Path) -> Path:
    """Get the root of the git repository containing path."""
    out = run_git(["rev-parse", "--show-toplevel"], cwd=path)
    return Path(out)


def get_main_branch(cwd: Path) -> str:
    """Detect the main branch name (main or master)."""
    try:
        run_git(["rev-parse", "--verify", "main"], cwd=cwd)
        return "main"
    except GitError:
        try:
            run_git(["rev-parse", "--verify", "master"], cwd=cwd)
            return "master"
        except GitError:
            return "main"


def create_worktree(
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    start_point: str | None = None,
) -> None:
    """Create a new git worktree with a new branch, or reattach an existing branch.

    If ``start_point`` is set, a new branch is created starting at that ref (when
    the branch does not exist yet). Ignored when the branch already exists.
    """
    # Prune stale worktree entries (e.g. directory was deleted externally)
    run_git(["worktree", "prune"], cwd=repo_root)

    # Check if branch already exists
    try:
        run_git(["rev-parse", "--verify", branch], cwd=repo_root)
        # Branch exists — attach worktree to it without creating a new branch
        run_git(
            ["worktree", "add", str(worktree_path), branch],
            cwd=repo_root,
        )
    except GitError:
        # Branch does not exist — create new branch
        args = ["worktree", "add", "-b", branch, str(worktree_path)]
        if start_point:
            run_git(["rev-parse", "--verify", start_point], cwd=repo_root)
            args.append(start_point)
        run_git(args, cwd=repo_root)


def create_detached_worktree(repo_root: Path, worktree_path: Path, ref: str) -> None:
    """Create a detached worktree at an existing ref."""
    run_git(["worktree", "prune"], cwd=repo_root)
    run_git(["rev-parse", "--verify", ref], cwd=repo_root)
    run_git(["worktree", "add", "--detach", str(worktree_path), ref], cwd=repo_root)


def checkout_detached(cwd: Path, ref: str) -> None:
    """Checkout a ref in detached mode in an existing worktree."""
    run_git(["rev-parse", "--verify", ref], cwd=cwd)
    run_git(["checkout", "--detach", ref], cwd=cwd)


def ref_exists(repo_root: Path, ref: str) -> bool:
    """Return True if a ref can be resolved."""
    try:
        run_git(["rev-parse", "--verify", ref], cwd=repo_root)
        return True
    except GitError:
        return False


def current_branch(cwd: Path) -> str:
    """Return the current branch name, or HEAD if detached."""
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


def remove_worktree(repo_root: Path, worktree_path: Path, branch: str | None = None) -> None:
    """Remove a git worktree."""
    run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_root)
    branch_candidates = [b for b in [branch, worktree_path.name, f"agvv/{worktree_path.name}"] if b]
    for branch_name in branch_candidates:
        try:
            run_git(["branch", "-D", branch_name], cwd=repo_root)
            break
        except GitError:
            continue


def merge_branch(repo_root: Path, branch: str) -> str:
    """Merge a branch into the current branch. Returns merge commit hash."""
    run_git(["merge", branch, "--no-ff", "-m", f"Merge {branch}"], cwd=repo_root)
    return run_git(["rev-parse", "HEAD"], cwd=repo_root)


def get_latest_commit(cwd: Path) -> str:
    """Get the latest commit hash."""
    return run_git(["rev-parse", "HEAD"], cwd=cwd)


def worktree_list(repo_root: Path) -> list[str]:
    """List all worktree paths."""
    out = run_git(["worktree", "list", "--porcelain"], cwd=repo_root)
    paths = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(line.split(" ", 1)[1])
    return paths


def conflict_files(repo_root: Path) -> list[str]:
    """Return files currently in merge conflict."""
    out = run_git(["diff", "--name-only", "--diff-filter=U"], cwd=repo_root)
    return [line for line in out.splitlines() if line.strip()]
