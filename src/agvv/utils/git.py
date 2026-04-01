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


def is_git_repo(path: Path) -> bool:
    """Return True when ``path`` is inside a Git work tree."""
    try:
        return run_git(["rev-parse", "--is-inside-work-tree"], cwd=path) == "true"
    except GitError:
        return False


def init_repo(path: Path, main_branch: str = "main") -> None:
    """Initialize a Git repository."""
    run_git(["init", "-b", main_branch], cwd=path)


def has_commits(cwd: Path) -> bool:
    """Return True when HEAD resolves to a commit."""
    try:
        run_git(["rev-parse", "--verify", "HEAD"], cwd=cwd)
        return True
    except GitError:
        return False


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
    start_ref: str | None = None,
) -> None:
    """Create a new git worktree with a new branch, or reattach an existing branch.

    If ``branch`` does not exist yet, it is created. When ``start_ref`` is set, the
    new branch starts at that commit-ish; otherwise it starts at the primary
    worktree's current HEAD.
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
        if start_ref:
            run_git(["rev-parse", "--verify", start_ref], cwd=repo_root)
            run_git(
                ["worktree", "add", "-b", branch, str(worktree_path), start_ref],
                cwd=repo_root,
            )
        else:
            run_git(
                ["worktree", "add", "-b", branch, str(worktree_path)],
                cwd=repo_root,
            )


def create_detached_worktree(repo_root: Path, worktree_path: Path, ref: str) -> None:
    """Create a detached worktree at an existing ref."""
    run_git(["worktree", "prune"], cwd=repo_root)
    run_git(["rev-parse", "--verify", ref], cwd=repo_root)
    run_git(["worktree", "add", "--detach", str(worktree_path), ref], cwd=repo_root)


def checkout_detached(cwd: Path, ref: str) -> None:
    """Checkout a ref in detached mode in an existing worktree."""
    run_git(["rev-parse", "--verify", ref], cwd=cwd)
    run_git(["checkout", "--detach", ref], cwd=cwd)


def checkout_branch(cwd: Path, branch: str, start_ref: str | None = None) -> None:
    """Attach the current worktree to ``branch``, creating it when needed."""
    if ref_exists(cwd, branch):
        run_git(["checkout", branch], cwd=cwd)
        return

    args = ["checkout", "-b", branch]
    if start_ref:
        run_git(["rev-parse", "--verify", start_ref], cwd=cwd)
        args.append(start_ref)
    run_git(args, cwd=cwd)


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


def changed_paths(cwd: Path) -> list[str]:
    """Return changed paths from ``git status --porcelain``."""
    out = run_git(["status", "--porcelain"], cwd=cwd)
    paths: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def is_worktree_clean(cwd: Path, ignored_paths: tuple[str, ...] = ()) -> bool:
    """Return True when the work tree has no relevant changes."""
    for path in changed_paths(cwd):
        if any(path == ignored or path.startswith(f"{ignored}/") for ignored in ignored_paths):
            continue
        return False
    return True


def has_staged_changes(cwd: Path) -> bool:
    """Return True when the index contains staged changes."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 1


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
