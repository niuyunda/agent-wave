"""Project/worktree layout and lifecycle operations."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agvv.orchestration.executor import run_git, run_git_success
from agvv.orchestration.models import LayoutPaths
from agvv.shared.errors import AgvvError

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def layout_paths(project_name: str, base_dir: Path, feature: str | None = None) -> LayoutPaths:
    """Construct canonical path objects for a project and optional feature."""

    project_dir = base_dir / project_name
    return LayoutPaths(
        project_dir=project_dir,
        repo_dir=project_dir / "repo.git",
        main_dir=project_dir / "main",
        feature_dir=(project_dir / feature) if feature else None,
    )


def _ensure_layout_name(value: str, label: str) -> None:
    """Ensure a project/feature/directory name is safe for this layout."""

    if not value:
        raise AgvvError(f"{label} cannot be empty.")
    if "/" in value or "\\" in value:
        raise AgvvError(f"{label} '{value}' must not contain path separators.")
    if ".." in Path(value).parts:
        raise AgvvError(f"{label} '{value}' must not contain path traversal segments.")
    if _SAFE_NAME_RE.fullmatch(value) is None:
        raise AgvvError(
            f"{label} '{value}' contains invalid characters. Use only letters, numbers, hyphens, and underscores."
        )


def _ensure_feature_name(feature: str) -> None:
    """Reject reserved feature names that collide with layout directories."""

    _ensure_layout_name(feature, "Feature branch name")
    if feature in {"main", "repo.git"}:
        raise AgvvError(f"Feature branch name '{feature}' is reserved in this layout.")


def _ensure_create_dir_value(directory: str) -> None:
    """Validate a create_dirs entry while allowing safe nested paths."""

    if not directory:
        raise AgvvError("Directory name cannot be empty.")
    if directory.startswith(("/", "\\")):
        raise AgvvError(f"Directory name '{directory}' must be a relative path.")
    normalized = directory.replace("\\", "/")
    parts = normalized.split("/")
    for part in parts:
        if not part or part in {".", ".."}:
            raise AgvvError(f"Directory name '{directory}' contains unsafe path segments.")
        if _SAFE_NAME_RE.fullmatch(part) is None:
            raise AgvvError(
                f"Directory name '{directory}' contains invalid characters. "
                "Use only letters, numbers, hyphens, underscores, and separators between segments."
            )


def _write_json(path: Path, data: dict) -> None:
    """Write JSON to disk with stable formatting and trailing newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_branch(repo_dir: Path) -> str:
    """Pick a default branch from a bare repo, preferring main/master."""

    branches_raw = run_git(["-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"]).stdout
    branches = [line.strip() for line in branches_raw.splitlines() if line.strip()]
    if not branches:
        raise AgvvError("No branches found in bare repo.")
    for preferred in ("main", "master"):
        if preferred in branches:
            return preferred
    return branches[0]


def init_project(project_name: str, base_dir: Path) -> LayoutPaths:
    """Initialize a project as bare repository plus ``main`` worktree."""

    _ensure_layout_name(project_name, "Project name")
    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if not paths.repo_dir.exists():
        run_git(["init", "--bare", str(paths.repo_dir)])

    if not paths.main_dir.exists():
        if run_git_success(["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", "refs/heads/main"]):
            run_git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), "main"])
        else:
            run_git(["-C", str(paths.repo_dir), "worktree", "add", "-b", "main", str(paths.main_dir)])

    if not run_git_success(["-C", str(paths.main_dir), "rev-parse", "--verify", "HEAD"]):
        run_git(["-C", str(paths.main_dir), "config", "user.email", "agvv@example.invalid"])
        run_git(["-C", str(paths.main_dir), "config", "user.name", "Agent Wave"])
        run_git(["-C", str(paths.main_dir), "commit", "--allow-empty", "-m", "init: bare repo setup"])

    return paths


def adopt_project(existing_repo: Path, project_name: str, base_dir: Path) -> tuple[LayoutPaths, str]:
    """Mirror an existing repository into the Agent Wave layout."""

    _ensure_layout_name(project_name, "Project name")
    if not (existing_repo / ".git").exists():
        raise AgvvError(f"{existing_repo} is not a git repository.")

    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if paths.repo_dir.exists() or paths.main_dir.exists():
        raise AgvvError(
            f"Target project already initialized at {paths.project_dir}. "
            "Use a different project name or clean target first."
        )

    # Use --bare instead of --mirror so later `git push <remote> <branch>`
    # remains valid. `--mirror` sets remote.origin.mirror=true, which makes
    # branch refspec pushes fail with:
    # "fatal: --mirror can't be combined with refspecs".
    run_git(["clone", "--bare", str(existing_repo), str(paths.repo_dir)])

    # If source repo has an upstream origin URL, preserve it so adopted tasks
    # push to the original remote instead of the local source path.
    if run_git_success(["-C", str(existing_repo), "config", "--get", "remote.origin.url"]):
        source_origin = run_git(["-C", str(existing_repo), "config", "--get", "remote.origin.url"]).stdout.strip()
        if source_origin:
            run_git(["-C", str(paths.repo_dir), "remote", "set-url", "origin", source_origin])

    branch = _default_branch(paths.repo_dir)
    run_git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), branch])
    return paths, branch


def start_feature(
    project_name: str,
    feature: str,
    base_dir: Path,
    from_branch: str,
    agent: str | None,
    task_id: str | None,
    ticket: str | None,
    params: dict[str, str],
    create_dirs: list[str],
) -> LayoutPaths:
    """Create or attach a feature worktree and persist task metadata."""

    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    if paths.feature_dir is None:
        raise RuntimeError(
            f"Internal error: missing feature directory for project={project_name}, base_dir={base_dir}, feature={feature}."
        )

    if not paths.repo_dir.exists() or not paths.main_dir.exists():
        raise AgvvError(
            f"Project not initialized at {paths.project_dir}. "
            "Initialize the project layout before starting a feature."
        )

    if paths.feature_dir.exists():
        raise AgvvError(f"Feature worktree path already exists: {paths.feature_dir}")

    branch_exists = run_git_success(
        ["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]
    )
    if branch_exists:
        run_git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.feature_dir), feature])
    else:
        run_git(["-C", str(paths.repo_dir), "worktree", "add", "-b", feature, str(paths.feature_dir), from_branch])

    feature_root = paths.feature_dir.resolve()
    for directory in create_dirs:
        _ensure_create_dir_value(directory)
        target = (paths.feature_dir / directory).resolve()
        if not target.is_relative_to(feature_root):
            raise AgvvError(
                f"Refusing to create directory outside feature worktree: '{directory}' resolved to '{target}'."
            )
        target.mkdir(parents=True, exist_ok=True)

    metadata = {
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "project_name": project_name,
        "feature": feature,
        "base_dir": str(base_dir),
        "from_branch": from_branch,
        "agent": agent,
        "task_id": task_id,
        "ticket": ticket,
        "params": params,
        "created_dirs": create_dirs,
    }
    _write_json(paths.feature_dir / ".agvv" / "context.json", metadata)
    return paths


def _feature_cleanup_paths(project_name: str, feature: str, base_dir: Path) -> LayoutPaths:
    """Resolve and validate feature cleanup paths for a project."""

    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    if paths.feature_dir is None:
        raise RuntimeError(
            f"Internal error: missing feature directory for project={project_name}, base_dir={base_dir}, feature={feature}."
        )
    if not paths.repo_dir.exists():
        raise AgvvError(f"Repo not found: {paths.repo_dir}")
    return paths


def _remove_feature_worktree(paths: LayoutPaths, *, allow_dirty: bool) -> None:
    """Remove a feature worktree, optionally enforcing clean git status."""

    if paths.feature_dir is None or not paths.feature_dir.exists():
        return
    if not allow_dirty:
        has_tracked_changes = not run_git_success(["-C", str(paths.feature_dir), "diff", "--quiet"])
        has_staged_changes = not run_git_success(["-C", str(paths.feature_dir), "diff", "--cached", "--quiet"])
        untracked_raw = run_git(
            ["-C", str(paths.feature_dir), "status", "--porcelain", "--untracked-files=all"]
        ).stdout
        has_untracked_files = any(
            line.startswith("?? ") and not line.startswith("?? .agvv/")
            for line in untracked_raw.splitlines()
        )
        if has_tracked_changes or has_staged_changes or has_untracked_files:
            raise AgvvError(
                f"Feature worktree has uncommitted changes at {paths.feature_dir}. "
                "Commit, stash, or discard changes before cleanup."
            )
    run_git(["-C", str(paths.repo_dir), "worktree", "remove", str(paths.feature_dir), "--force"])


def _remove_feature_branch(paths: LayoutPaths, feature: str, *, delete_branch: bool) -> None:
    """Delete feature branch when requested and still present."""

    if not delete_branch:
        return
    if run_git_success(["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]):
        run_git(["-C", str(paths.repo_dir), "branch", "-D", feature])


def cleanup_feature(
    project_name: str,
    feature: str,
    base_dir: Path,
    delete_branch: bool,
) -> LayoutPaths:
    """Remove a feature worktree and optionally delete its branch."""

    paths = _feature_cleanup_paths(project_name, feature, base_dir)
    _remove_feature_worktree(paths, allow_dirty=False)
    _remove_feature_branch(paths, feature, delete_branch=delete_branch)
    return paths


def cleanup_feature_force(
    project_name: str,
    feature: str,
    base_dir: Path,
    delete_branch: bool,
) -> LayoutPaths:
    """Force-remove a feature worktree and optionally delete its branch."""

    paths = _feature_cleanup_paths(project_name, feature, base_dir)
    _remove_feature_worktree(paths, allow_dirty=True)
    _remove_feature_branch(paths, feature, delete_branch=delete_branch)
    return paths
