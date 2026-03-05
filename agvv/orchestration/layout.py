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


def layout_paths(
    project_name: str, base_dir: Path, feature: str | None = None
) -> LayoutPaths:
    """Construct canonical path objects for a project and optional feature."""
    project_dir = base_dir / project_name
    return LayoutPaths(
        project_dir=project_dir,
        repo_dir=project_dir / "repo.git",
        main_dir=project_dir / "main",
        feature_dir=(project_dir / feature) if feature else None,
    )


def _ensure_layout_name(value: str, label: str) -> None:
    """Ensure a project/feature name is safe for this layout."""
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
    """Validate that the feature name is safe and not reserved by layout internals."""
    _ensure_layout_name(feature, "Feature branch name")
    if feature in {"main", "repo.git"}:
        raise AgvvError(f"Feature branch name '{feature}' is reserved in this layout.")


def _write_json(path: Path, data: dict) -> None:
    """Write JSON data with deterministic formatting and a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_branch(repo_dir: Path) -> str:
    """Choose the default branch from a bare repo, preferring main/master."""
    head_branch: str | None = None
    if run_git_success(
        ["-C", str(repo_dir), "symbolic-ref", "--quiet", "--short", "HEAD"]
    ):
        resolved = run_git(
            ["-C", str(repo_dir), "symbolic-ref", "--quiet", "--short", "HEAD"]
        ).stdout.strip()
        if resolved:
            head_branch = resolved

    branches_raw = run_git(
        ["-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    ).stdout
    branches = [line.strip() for line in branches_raw.splitlines() if line.strip()]
    if not branches:
        raise AgvvError("No branches found in bare repo.")
    if head_branch and head_branch in branches:
        return head_branch
    for preferred in ("main", "master"):
        if preferred in branches:
            return preferred
    return branches[0]


def _is_bare_repo(path: Path) -> bool:
    """Return True when path is an accessible bare git repository."""
    if not path.exists() or not path.is_dir():
        return False
    if not run_git_success(["-C", str(path), "rev-parse", "--is-bare-repository"]):
        return False
    return (
        run_git(["-C", str(path), "rev-parse", "--is-bare-repository"]).stdout.strip()
        == "true"
    )


def _resolve_adopt_source_repo(existing_repo: Path) -> Path:
    """Resolve adopt source repository path from user-provided existing_repo."""
    if not existing_repo.exists() or not existing_repo.is_dir():
        raise AgvvError(f"Project directory not found: {existing_repo}")

    if (existing_repo / ".git").exists():
        return existing_repo

    if _is_bare_repo(existing_repo):
        return existing_repo

    first_level_git_entries = sorted(
        child for child in existing_repo.iterdir() if child.name.endswith(".git")
    )
    if not first_level_git_entries:
        raise AgvvError(
            f"{existing_repo} is not a git repository. "
            "No '*.git' entry found in the first-level directory."
        )
    if len(first_level_git_entries) > 1:
        candidates = ", ".join(entry.name for entry in first_level_git_entries)
        raise AgvvError(
            f"{existing_repo} has multiple '*.git' entries: {candidates}. "
            "Pass a specific repository path via --project-dir."
        )
    candidate = first_level_git_entries[0]
    if not _is_bare_repo(candidate):
        raise AgvvError(
            f"Found first-level '*.git' entry at {candidate}, but it is not a bare git repository."
        )
    return candidate


def init_project(project_name: str, base_dir: Path) -> LayoutPaths:
    """Initialize a project as bare repository plus main worktree."""
    _ensure_layout_name(project_name, "Project name")
    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if not paths.repo_dir.exists():
        run_git(["init", "--bare", str(paths.repo_dir)])

    if not paths.main_dir.exists():
        if run_git_success(
            [
                "-C",
                str(paths.repo_dir),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/main",
            ]
        ):
            run_git(
                [
                    "-C",
                    str(paths.repo_dir),
                    "worktree",
                    "add",
                    str(paths.main_dir),
                    "main",
                ]
            )
        else:
            run_git(
                [
                    "-C",
                    str(paths.repo_dir),
                    "worktree",
                    "add",
                    "-b",
                    "main",
                    str(paths.main_dir),
                ]
            )

    if not run_git_success(
        ["-C", str(paths.main_dir), "rev-parse", "--verify", "HEAD"]
    ):
        run_git(
            ["-C", str(paths.main_dir), "config", "user.email", "agvv@example.invalid"]
        )
        run_git(["-C", str(paths.main_dir), "config", "user.name", "Agent Wave"])
        run_git(
            [
                "-C",
                str(paths.main_dir),
                "commit",
                "--allow-empty",
                "-m",
                "init: bare repo setup",
            ]
        )

    return paths


def adopt_project(
    existing_repo: Path, project_name: str, base_dir: Path
) -> tuple[LayoutPaths, str]:
    """Adopt an existing repository into Agent Wave layout."""
    _ensure_layout_name(project_name, "Project name")
    source_repo = _resolve_adopt_source_repo(existing_repo)

    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if paths.repo_dir.exists() or paths.main_dir.exists():
        raise AgvvError(
            f"Target project already initialized at {paths.project_dir}. "
            "Use a different project name or clean target first."
        )

    run_git(["clone", "--bare", str(source_repo), str(paths.repo_dir)])

    if run_git_success(
        ["-C", str(source_repo), "config", "--get", "remote.origin.url"]
    ):
        source_origin = run_git(
            ["-C", str(source_repo), "config", "--get", "remote.origin.url"]
        ).stdout.strip()
        if source_origin:
            run_git(
                [
                    "-C",
                    str(paths.repo_dir),
                    "remote",
                    "set-url",
                    "origin",
                    source_origin,
                ]
            )

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
) -> LayoutPaths:
    """Create or attach a feature worktree and persist task metadata."""
    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    if paths.feature_dir is None:
        raise RuntimeError(
            f"Internal error: missing feature directory for project={project_name}, feature={feature}."
        )

    if not paths.repo_dir.exists() or not paths.main_dir.exists():
        init_project(project_name, base_dir)

    if paths.feature_dir.exists():
        raise AgvvError(f"Feature worktree path already exists: {paths.feature_dir}")

    branch_exists = run_git_success(
        [
            "-C",
            str(paths.repo_dir),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{feature}",
        ]
    )
    if branch_exists:
        run_git(
            [
                "-C",
                str(paths.repo_dir),
                "worktree",
                "add",
                str(paths.feature_dir),
                feature,
            ]
        )
    else:
        run_git(
            [
                "-C",
                str(paths.repo_dir),
                "worktree",
                "add",
                "-b",
                feature,
                str(paths.feature_dir),
                from_branch,
            ]
        )

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
    }
    _write_json(paths.feature_dir / ".agvv" / "context.json", metadata)
    return paths


def _feature_cleanup_paths(
    project_name: str, feature: str, base_dir: Path
) -> LayoutPaths:
    """Resolve and validate layout paths needed for feature cleanup operations."""
    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    if paths.feature_dir is None:
        raise RuntimeError(
            f"Internal error: missing feature directory for project={project_name}, feature={feature}."
        )
    if not paths.repo_dir.exists():
        raise AgvvError(f"Repo not found: {paths.repo_dir}")
    return paths


def _remove_feature_worktree(paths: LayoutPaths, *, allow_dirty: bool) -> None:
    """Remove a feature worktree, optionally refusing when there are local changes."""
    if paths.feature_dir is None or not paths.feature_dir.exists():
        return
    if not allow_dirty:
        has_tracked_changes = not run_git_success(
            ["-C", str(paths.feature_dir), "diff", "--quiet"]
        )
        has_staged_changes = not run_git_success(
            ["-C", str(paths.feature_dir), "diff", "--cached", "--quiet"]
        )
        untracked_raw = run_git(
            [
                "-C",
                str(paths.feature_dir),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ]
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
    run_git(
        [
            "-C",
            str(paths.repo_dir),
            "worktree",
            "remove",
            str(paths.feature_dir),
            "--force",
        ]
    )


def _remove_feature_branch(
    paths: LayoutPaths, feature: str, *, delete_branch: bool
) -> None:
    """Delete the feature branch in the bare repo when deletion is requested."""
    if not delete_branch:
        return
    if run_git_success(
        [
            "-C",
            str(paths.repo_dir),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{feature}",
        ]
    ):
        run_git(["-C", str(paths.repo_dir), "branch", "-D", feature])


def cleanup_feature(
    project_name: str, feature: str, base_dir: Path, delete_branch: bool
) -> LayoutPaths:
    """Remove a feature worktree and optionally delete its branch."""
    paths = _feature_cleanup_paths(project_name, feature, base_dir)
    _remove_feature_worktree(paths, allow_dirty=False)
    _remove_feature_branch(paths, feature, delete_branch=delete_branch)
    return paths


def cleanup_feature_force(
    project_name: str, feature: str, base_dir: Path, delete_branch: bool
) -> LayoutPaths:
    """Force-remove a feature worktree and optionally delete its branch."""
    paths = _feature_cleanup_paths(project_name, feature, base_dir)
    _remove_feature_worktree(paths, allow_dirty=True)
    _remove_feature_branch(paths, feature, delete_branch=delete_branch)
    return paths
