"""Project/worktree layout and lifecycle operations.

Layout convention:
    <project>/
        # project files (main/default worktree lives directly here)
        .git/                 # git repository metadata
        worktrees/             # extra task worktrees only
            feat-<slug>/      # feature worktree directories
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agvv.orchestration.executor import run_git, run_git_success
from agvv.orchestration.models import LayoutPaths
from agvv.shared.errors import AgvvError

_FEATURE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")
_RESERVED_FEATURE_NAMES = frozenset({"main", "worktrees"})


def layout_paths(
    project_name: str, base_dir: Path, feature: str | None = None
) -> LayoutPaths:
    """Construct canonical path objects for a project and optional feature.

    The project directory IS the main worktree root. Feature worktrees live
    under <project>/worktrees/<feat-slug>/.
    """
    project_dir = base_dir / project_name
    return LayoutPaths(
        project_dir=project_dir,
        repo_dir=project_dir / ".git",
        main_dir=project_dir,  # main worktree IS the project root
        worktrees_dir=project_dir / "worktrees",
        feature_dir=(project_dir / "worktrees" / _feature_to_dirname(feature))
        if feature
        else None,
    )


def _feature_to_dirname(feature: str) -> str:
    """Convert a feature name to a safe directory name (use - instead of /)."""
    return feature.replace("/", "-")


def _ensure_layout_name(value: str, label: str) -> None:
    """Ensure a project name is safe for this layout."""
    if not value:
        raise AgvvError(f"{label} cannot be empty.")
    if "\\" in value:
        raise AgvvError(f"{label} '{value}' must not contain backslashes.")
    if ".." in Path(value).parts:
        raise AgvvError(f"{label} '{value}' must not contain '..'.")
    if not re.match(r"^[A-Za-z0-9_-]+$", value):
        raise AgvvError(
            f"{label} '{value}' contains invalid characters. "
            "Use only letters, numbers, hyphens, and underscores."
        )


def _ensure_feature_name(feature: str) -> None:
    """Validate that the feature name is safe and not reserved by layout internals.

    Allows slash-separated compound names (e.g. feat/demo) for the branch-style
    naming convention, but reserves layout directory names.
    """
    if not feature:
        raise AgvvError("Feature branch name cannot be empty.")
    if "\\" in feature:
        raise AgvvError(
            f"Feature branch name '{feature}' must not contain backslashes."
        )
    if ".." in Path(feature).parts:
        raise AgvvError(f"Feature branch name '{feature}' must not contain '..'.")
    if _FEATURE_NAME_RE.fullmatch(feature) is None:
        raise AgvvError(
            f"Feature branch name '{feature}' contains invalid characters. "
            "Use only letters, numbers, hyphens, underscores, and slashes "
            "(e.g. feat/demo or fix-bug)."
        )
    if feature in _RESERVED_FEATURE_NAMES:
        raise AgvvError(
            f"Feature branch name '{feature}' is reserved in this layout "
            "(main worktree or worktrees directory)."
        )


def _write_json(path: Path, data: dict) -> None:
    """Write JSON data with deterministic formatting and a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_branch(repo_dir: Path) -> str:
    """Choose the default branch from a repo, preferring main/master."""
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
        raise AgvvError("No branches found in repository.")
    if head_branch and head_branch in branches:
        return head_branch
    for preferred in ("main", "master"):
        if preferred in branches:
            return preferred
    return branches[0]


def _resolve_adopt_source_repo(existing_repo: Path) -> Path:
    """Resolve adopt source repository path from user-provided existing_repo.

    Handles:
    - Regular git repo: <project>/.git/
    - Bare repo: <project>.git/ (HEAD exists, no .git subdirectory)
    - Git worktree: <project>/ with .git as a gitlink file (rejected)
    """
    if not existing_repo.exists() or not existing_repo.is_dir():
        raise AgvvError(f"Project directory not found: {existing_repo}")

    git_entry = existing_repo / ".git"

    # Regular git repo: .git is a subdirectory.
    if git_entry.is_dir():
        return existing_repo

    # Git worktree: .git is a gitlink file.
    if git_entry.is_file():
        raise AgvvError(
            f"{existing_repo} appears to be a linked git worktree (.git is a file). "
            "Pass the primary repository path via --project-dir."
        )

    # Bare repo: HEAD exists but .git is not a subdirectory.
    if (existing_repo / "HEAD").exists() and not git_entry.exists():
        return existing_repo

    first_level_git_entries = sorted(
        child for child in existing_repo.iterdir() if child.name.endswith(".git")
    )
    if not first_level_git_entries:
        raise AgvvError(
            f"{existing_repo} is not a git repository. "
            "No '.git' entry found in the first-level directory."
        )
    if len(first_level_git_entries) > 1:
        candidates = ", ".join(entry.name for entry in first_level_git_entries)
        raise AgvvError(
            f"{existing_repo} has multiple '*.git' entries: {candidates}. "
            "Pass a specific repository path via --project-dir."
        )
    candidate = first_level_git_entries[0]
    # Regular .git directory.
    if (candidate / "HEAD").exists():
        return candidate.parent
    raise AgvvError(
        f"Found '*.git' entry at {candidate}, but it does not appear "
        "to be a valid git repository (no HEAD file)."
    )


def _exclude_worktrees(main_dir: Path) -> None:
    """Add /worktrees/ to .git/info/exclude in the main worktree."""
    exclude_path = main_dir / ".git" / "info" / "exclude"
    if not exclude_path.exists():
        return
    marker = "/worktrees/\n"
    content = exclude_path.read_text(encoding="utf-8")
    if marker not in content:
        exclude_path.write_text(content + marker, encoding="utf-8")


def init_project(project_name: str, base_dir: Path) -> LayoutPaths:
    """Initialize a project as a regular git repository.

    The project directory itself becomes the main worktree (no nested main/).
    Feature worktrees live under <project>/worktrees/<feat-slug>/.

    Sequence:
        mkdir <project>
        git init -b main <project>
        mkdir <project>/worktrees
        printf "/worktrees/\n" >> .git/info/exclude
        [optional initial commit]
    """
    _ensure_layout_name(project_name, "Project name")
    paths = layout_paths(project_name, base_dir)

    if paths.repo_dir.exists():
        # Already initialized.
        return paths

    paths.project_dir.mkdir(parents=True, exist_ok=True)

    # Initialize a regular git repo; the project dir IS the main worktree.
    run_git(["init", "-b", "main", str(paths.project_dir)])

    # Configure identity if not already set.
    if not run_git_success(
        ["-C", str(paths.project_dir), "config", "--get", "user.email"]
    ):
        run_git(
            [
                "-C",
                str(paths.project_dir),
                "config",
                "user.email",
                "agvv@example.invalid",
            ]
        )
        run_git(["-C", str(paths.project_dir), "config", "user.name", "Agent Wave"])

    # Create initial commit if the repo is still empty (no HEAD).
    if not run_git_success(
        ["-C", str(paths.project_dir), "rev-parse", "--verify", "HEAD"]
    ):
        run_git(
            [
                "-C",
                str(paths.project_dir),
                "commit",
                "--allow-empty",
                "-m",
                "init: project setup",
            ]
        )

    # Create worktrees/ directory and exclude it from the main worktree.
    paths.worktrees_dir.mkdir(parents=True, exist_ok=True)
    _exclude_worktrees(paths.main_dir)

    return paths


def adopt_project(
    existing_repo: Path, project_name: str, base_dir: Path
) -> tuple[LayoutPaths, str]:
    """Adopt an existing regular git repository into Agent Wave layout.

    The existing repository's history is cloned into the new project directory.
    The project directory becomes the main worktree. If the existing directory
    is itself a git worktree (has .git gitlink), this is a conflict — stop
    and report to orchestrator.
    """
    _ensure_layout_name(project_name, "Project name")
    source_repo = _resolve_adopt_source_repo(existing_repo)

    paths = layout_paths(project_name, base_dir)

    if paths.repo_dir.exists():
        raise AgvvError(
            f"Target project already initialized (.git exists) at {paths.project_dir}. "
            "Use a different project name or clean the target first."
        )

    paths.project_dir.mkdir(parents=True, exist_ok=True)

    # Clone the source repo into project_dir (regular clone, not bare).
    run_git(["clone", str(source_repo), str(paths.project_dir)])

    # Transfer remote origin if present on source.
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
                    str(paths.project_dir),
                    "remote",
                    "set-url",
                    "origin",
                    source_origin,
                ]
            )

    branch = _default_branch(paths.repo_dir)

    # Create worktrees/ directory and exclude it from the main worktree.
    paths.worktrees_dir.mkdir(parents=True, exist_ok=True)
    _exclude_worktrees(paths.main_dir)

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

    if not paths.repo_dir.exists():
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
    """Delete the feature branch in the repo when deletion is requested."""
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
