"""Core orchestration primitives for the Agent Wave CLI."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
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


@dataclass(frozen=True)
class PrCheckResult:
    """Simplified PR check result for short review cycles."""

    status: str
    reason: str
    state: str
    review_decision: str | None


@dataclass(frozen=True)
class PrWaitResult:
    """Result of polling a PR for status updates."""

    result: PrCheckResult
    attempts: int
    timed_out: bool


@dataclass(frozen=True)
class PrNextAction:
    """Suggested next action for a PR based on current status."""

    status: str
    action: str
    note: str


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
    except FileNotFoundError as exc:
        raise AgvvError(f"Command not found: {cmd[0]}") from exc
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

    if not isinstance(raw, dict):
        raise AgvvError("Invalid task registry entry; each task must be an object.")

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
    except OSError as exc:
        raise AgvvError(f"Failed to read task registry at {registry_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AgvvError(f"Task registry JSON is invalid at {registry_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise AgvvError(f"Task registry root must be an object at {registry_path}.")

    version = payload.get("version", 1)
    try:
        parsed_version = int(version)
    except (TypeError, ValueError) as exc:
        raise AgvvError(f"Task registry field 'version' must be an integer at {registry_path}: {exc}") from exc

    tasks_raw = payload.get("tasks", [])
    if not isinstance(tasks_raw, list):
        raise AgvvError(f"Task registry field 'tasks' must be a list at {registry_path}.")

    tasks = [_coerce_task_record(item) for item in tasks_raw]
    updated_at = str(payload.get("updated_at", datetime.now(tz=timezone.utc).isoformat()))
    return TaskRegistry(version=parsed_version, updated_at=updated_at, tasks=tasks)


def _parse_task_updated_at(value: str | None) -> datetime:
    """Parse task timestamp for stable chronological sorting."""

    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


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
    return sorted(tasks, key=lambda item: _parse_task_updated_at(item.updated_at), reverse=True)


def _task_record_to_dict(task: TaskRecord) -> dict[str, Any]:
    """Convert a ``TaskRecord`` into JSON-serializable dictionary payload."""

    return {
        "id": task.id,
        "project_name": task.project_name,
        "feature": task.feature,
        "status": task.status,
        "session": task.session,
        "agent": task.agent,
        "updated_at": task.updated_at,
    }


def save_task_registry(registry: TaskRegistry, path: Path | None = None) -> Path:
    """Persist task registry atomically and return the target path."""

    target = resolve_tasks_path(path)
    payload = {
        "version": registry.version,
        "updated_at": registry.updated_at,
        "tasks": [_task_record_to_dict(task) for task in registry.tasks],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(target)
    return target


def tmux_session_exists(session: str) -> bool:
    """Return whether a tmux session exists."""

    try:
        result = subprocess.run(["tmux", "has-session", "-t", session], check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AgvvError("tmux not found") from exc
    return result.returncode == 0


def tmux_kill_session(session: str) -> None:
    """Kill tmux session if it exists."""

    if not tmux_session_exists(session):
        return
    _run(["tmux", "kill-session", "-t", session])


def tmux_new_session(session: str, cwd: Path, command: str) -> None:
    """Start a detached tmux session executing command in cwd."""

    if tmux_session_exists(session):
        raise AgvvError(f"tmux session already exists: {session}")
    quoted_cwd = shlex.quote(str(cwd))
    _run(["tmux", "new-session", "-d", "-s", session, f"cd {quoted_cwd} && {command}"])


def create_orch_task(
    project_name: str,
    feature: str,
    base_dir: Path,
    task_id: str,
    session: str,
    agent: str,
    agent_cmd: str,
    from_branch: str = "main",
    tasks_path: Path | None = None,
) -> TaskRecord:
    """Create/start an orchestration task by preparing worktree + tmux + registry entry."""

    _ensure_layout_name(project_name, "Project name")
    _ensure_feature_name(feature)
    _ensure_layout_name(task_id, "Task id")
    _ensure_layout_name(session, "Session name")

    paths = layout_paths(project_name, base_dir, feature=feature)
    if not paths.repo_dir.exists() or not paths.main_dir.exists():
        raise AgvvError(
            f"Project not initialized at {paths.project_dir}. "
            "Run `agvv project init` or `agvv project adopt` first."
        )

    if paths.feature_dir is None:
        raise RuntimeError("Internal error: feature_dir resolved to None.")

    registry = load_task_registry(tasks_path)
    existing_ids = {task.id for task in registry.tasks}
    if task_id in existing_ids:
        raise AgvvError(f"Task id already exists: {task_id}")

    if tmux_session_exists(session):
        raise AgvvError(f"tmux session already exists: {session}")

    if not paths.feature_dir.exists():
        start_feature(
            project_name=project_name,
            feature=feature,
            base_dir=base_dir,
            from_branch=from_branch,
            agent=agent,
            task_id=task_id,
            ticket=None,
            params={"agent_cmd": agent_cmd},
            create_dirs=[],
        )

    created = TaskRecord(
        id=task_id,
        project_name=project_name,
        feature=feature,
        status="running",
        session=session,
        agent=agent,
        updated_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    tmux_new_session(session=session, cwd=paths.feature_dir, command=agent_cmd)
    try:
        updated_tasks = [created, *registry.tasks]
        save_task_registry(
            TaskRegistry(version=registry.version, updated_at=created.updated_at, tasks=updated_tasks),
            path=tasks_path,
        )
    except Exception:
        tmux_kill_session(session)
        raise

    return created


def retry_orch_task(
    task_id: str,
    base_dir: Path,
    agent_cmd: str,
    session: str | None = None,
    tasks_path: Path | None = None,
) -> TaskRecord:
    """Retry an existing orchestration task by relaunching tmux session and updating status."""

    registry = load_task_registry(tasks_path)
    index = -1
    current: TaskRecord | None = None
    for i, item in enumerate(registry.tasks):
        if item.id == task_id:
            index = i
            current = item
            break

    if current is None:
        raise AgvvError(f"Task not found: {task_id}")
    if current.status == "running":
        raise AgvvError(f"Task is already running: {task_id}")

    chosen_session = session or current.session
    if not chosen_session:
        raise AgvvError("Retry requires a tmux session name (provide --session).")
    if tmux_session_exists(chosen_session):
        raise AgvvError(f"tmux session already exists: {chosen_session}")

    paths = layout_paths(current.project_name, base_dir, feature=current.feature)
    if paths.feature_dir is None or not paths.feature_dir.exists():
        raise AgvvError(f"Feature worktree not found for retry: {current.project_name}/{current.feature}")

    tmux_new_session(session=chosen_session, cwd=paths.feature_dir, command=agent_cmd)

    updated = TaskRecord(
        id=current.id,
        project_name=current.project_name,
        feature=current.feature,
        status="running",
        session=chosen_session,
        agent=current.agent,
        updated_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    tasks = list(registry.tasks)
    tasks[index] = updated
    save_task_registry(TaskRegistry(version=registry.version, updated_at=updated.updated_at, tasks=tasks), path=tasks_path)
    return updated


def check_pr_status(repo: str, pr_number: int) -> PrCheckResult:
    """Check PR state via gh and map to minimal status for fast review loops."""

    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "state,mergedAt,reviewDecision,statusCheckRollup",
    ]
    try:
        payload = json.loads(_run(cmd).stdout)
    except json.JSONDecodeError as exc:
        raise AgvvError(f"Invalid JSON from gh pr view for {repo}#{pr_number}: {exc}") from exc

    state = str(payload.get("state", ""))
    merged_at = payload.get("mergedAt")
    review_decision = payload.get("reviewDecision")

    if merged_at:
        return PrCheckResult(status="done", reason="merged", state=state, review_decision=review_decision)

    if state != "OPEN":
        return PrCheckResult(status="closed", reason="not_open", state=state, review_decision=review_decision)

    if review_decision == "CHANGES_REQUESTED":
        return PrCheckResult(status="needs_work", reason="changes_requested", state=state, review_decision=review_decision)

    checks = payload.get("statusCheckRollup") or []
    failing = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    for check in checks:
        conclusion = str((check or {}).get("conclusion") or "")
        if conclusion in failing:
            return PrCheckResult(status="needs_work", reason=f"ci_{conclusion.lower()}", state=state, review_decision=review_decision)

    return PrCheckResult(status="waiting", reason="pending_review_or_ci", state=state, review_decision=review_decision)


def wait_pr_status(repo: str, pr_number: int, interval_seconds: int = 120, max_attempts: int = 30) -> PrWaitResult:
    """Poll PR status every interval until terminal or attempts exhausted."""

    if interval_seconds <= 0:
        raise AgvvError("interval_seconds must be > 0")
    if max_attempts <= 0:
        raise AgvvError("max_attempts must be > 0")

    last = check_pr_status(repo=repo, pr_number=pr_number)
    terminal = {"done", "closed", "needs_work"}
    attempts = 1
    while last.status not in terminal and attempts < max_attempts:
        time.sleep(interval_seconds)
        last = check_pr_status(repo=repo, pr_number=pr_number)
        attempts += 1

    return PrWaitResult(result=last, attempts=attempts, timed_out=last.status == "waiting")


def recommend_pr_next_action(repo: str, pr_number: int) -> PrNextAction:
    """Return a minimal next-step recommendation for PR automation loop."""

    result = check_pr_status(repo=repo, pr_number=pr_number)
    if result.status == "needs_work":
        return PrNextAction(
            status=result.status,
            action="retry",
            note="Run fix workflow: update code, push, then run `agvv pr wait` again.",
        )
    if result.status == "done":
        return PrNextAction(status=result.status, action="cleanup", note="PR merged; run feature cleanup.")
    if result.status == "closed":
        return PrNextAction(status=result.status, action="stop", note="PR closed without merge; manual follow-up needed.")
    return PrNextAction(
        status=result.status,
        action="wait",
        note="Keep polling with `agvv pr wait --interval-seconds 120 --max-attempts 30`.",
    )


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
