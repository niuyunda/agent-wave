"""Core orchestration primitives for the Agent Wave CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgvvError(RuntimeError):
    """Raised when an Agent Wave orchestration operation fails."""


@dataclass(frozen=True)
class LayoutPaths:
    """Resolved filesystem paths for a project/worktree layout."""

    project_dir: Path
    repo_dir: Path
    main_dir: Path
    feature_dir: Path | None = None


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TASKS_ENV_VAR = "AGVV_TASKS_PATH"
_DEFAULT_TASKS_PATH = Path("~/.agvv/tasks.json")


@dataclass(frozen=True)
class TaskRecord:
    """Single orchestration task record from the registry."""

    id: str
    project_name: str
    feature: str
    status: str
    session: str | None
    agent: str | None
    updated_at: str


@dataclass(frozen=True)
class TaskRegistry:
    """In-memory representation of the tasks registry."""

    version: int
    updated_at: str
    tasks: list[TaskRecord]


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a shell command and normalize failures into ``AgvvError``."""

    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AgvvError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        ) from exc


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Execute a git command with shared error handling."""

    return _run(["git", *args], cwd=cwd)


def _git_success(args: list[str], cwd: Path | None = None) -> bool:
    """Return whether a git command succeeds without raising."""

    try:
        _run(["git", *args], cwd=cwd)
        return True
    except AgvvError:
        return False


def parse_kv_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` CLI parameters into a dictionary."""

    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise AgvvError(f"Invalid --param value '{pair}'. Expected KEY=VALUE.")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise AgvvError(f"Invalid --param value '{pair}'. Key cannot be empty.")
        result[key] = value
    return result


def resolve_tasks_path(path: Path | None = None) -> Path:
    """Resolve tasks registry path from argument/env/default."""

    if path is not None:
        return path.expanduser().resolve()

    env_path = os.getenv(_TASKS_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser().resolve()

    return _DEFAULT_TASKS_PATH.expanduser().resolve()


def _coerce_task_record(raw: dict[str, Any]) -> TaskRecord:
    """Convert raw JSON task object into a typed ``TaskRecord``."""

    try:
        return TaskRecord(
            id=str(raw["id"]),
            project_name=str(raw["project_name"]),
            feature=str(raw["feature"]),
            status=str(raw["status"]),
            session=(str(raw["session"]) if raw.get("session") is not None else None),
            agent=(str(raw["agent"]) if raw.get("agent") is not None else None),
            updated_at=str(raw["updated_at"]),
        )
    except KeyError as exc:
        raise AgvvError(f"Invalid task registry entry; missing required key: {exc.args[0]}") from exc


def load_task_registry(path: Path | None = None) -> TaskRegistry:
    """Load task registry JSON from disk.

    Returns an empty registry if file does not exist.
    """

    registry_path = resolve_tasks_path(path)
    if not registry_path.exists():
        return TaskRegistry(version=1, updated_at=datetime.now(tz=timezone.utc).isoformat(), tasks=[])

    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgvvError(f"Task registry JSON is invalid at {registry_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise AgvvError(f"Task registry root must be an object at {registry_path}.")

    version = payload.get("version", 1)
    tasks_raw = payload.get("tasks", [])
    if not isinstance(tasks_raw, list):
        raise AgvvError(f"Task registry field 'tasks' must be a list at {registry_path}.")

    tasks = [_coerce_task_record(item) for item in tasks_raw]
    updated_at = str(payload.get("updated_at", datetime.now(tz=timezone.utc).isoformat()))
    return TaskRegistry(version=int(version), updated_at=updated_at, tasks=tasks)


def list_tasks(
    path: Path | None = None,
    project_name: str | None = None,
    status: str | None = None,
) -> list[TaskRecord]:
    """Return tasks from registry with optional project/status filters."""

    tasks = load_task_registry(path).tasks
    if project_name is not None:
        tasks = [task for task in tasks if task.project_name == project_name]
    if status is not None:
        tasks = [task for task in tasks if task.status == status]
    return sorted(tasks, key=lambda item: item.updated_at, reverse=True)


def layout_paths(project_name: str, base_dir: Path, feature: str | None = None) -> LayoutPaths:
    """Construct canonical path objects for a project and optional feature."""

    project_dir = base_dir / project_name
    return LayoutPaths(
        project_dir=project_dir,
        repo_dir=project_dir / "repo.git",
        main_dir=project_dir / "main",
        feature_dir=(project_dir / feature) if feature else None,
    )


def _ensure_feature_name(feature: str) -> None:
    """Reject reserved feature names that collide with layout directories."""

    _ensure_layout_name(feature, "Feature branch name")
    if feature in {"main", "repo.git"}:
        raise AgvvError(f"Feature branch name '{feature}' is reserved in this layout.")


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

    branches_raw = _git(["-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"]).stdout
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
        _git(["init", "--bare", str(paths.repo_dir)])

    if not paths.main_dir.exists():
        if _git_success(["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", "refs/heads/main"]):
            _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), "main"])
        else:
            _git(["-C", str(paths.repo_dir), "worktree", "add", "-b", "main", str(paths.main_dir)])

    if not _git_success(["-C", str(paths.main_dir), "rev-parse", "--verify", "HEAD"]):
        _git(["-C", str(paths.main_dir), "commit", "--allow-empty", "-m", "init: bare repo setup"])

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

    _git(["clone", "--mirror", str(existing_repo), str(paths.repo_dir)])
    branch = _default_branch(paths.repo_dir)
    _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), branch])
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
            "Run `agvv project init` or `agvv project adopt` first."
        )

    if paths.feature_dir.exists():
        raise AgvvError(f"Feature worktree path already exists: {paths.feature_dir}")

    branch_exists = _git_success(
        ["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]
    )
    if branch_exists:
        _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.feature_dir), feature])
    else:
        _git(["-C", str(paths.repo_dir), "worktree", "add", "-b", feature, str(paths.feature_dir), from_branch])

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


def cleanup_feature(
    project_name: str,
    feature: str,
    base_dir: Path,
    delete_branch: bool,
) -> LayoutPaths:
    """Remove a feature worktree and optionally delete its branch."""

    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    if paths.feature_dir is None:
        raise RuntimeError(
            f"Internal error: missing feature directory for project={project_name}, base_dir={base_dir}, feature={feature}."
        )

    if not paths.repo_dir.exists():
        raise AgvvError(f"Repo not found: {paths.repo_dir}")

    if paths.feature_dir.exists():
        has_tracked_changes = not _git_success(["-C", str(paths.feature_dir), "diff", "--quiet"])
        has_staged_changes = not _git_success(["-C", str(paths.feature_dir), "diff", "--cached", "--quiet"])
        if has_tracked_changes or has_staged_changes:
            raise AgvvError(
                f"Feature worktree has uncommitted changes at {paths.feature_dir}. "
                "Commit, stash, or discard changes before cleanup."
            )
        _git(["-C", str(paths.repo_dir), "worktree", "remove", str(paths.feature_dir), "--force"])

    if delete_branch and _git_success(
        ["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]
    ):
        _git(["-C", str(paths.repo_dir), "branch", "-D", feature])

    return paths
