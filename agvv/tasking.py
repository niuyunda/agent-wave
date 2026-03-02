"""Task-oriented orchestration for Agent Wave."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agvv.core import (
    AgvvError,
    check_pr_status,
    cleanup_feature,
    layout_paths,
    start_feature,
    summarize_pr_feedback,
    tmux_kill_session,
    tmux_new_session,
    tmux_session_exists,
)

_TASK_DB_ENV_VAR = "AGVV_DB_PATH"
_DEFAULT_TASK_DB_PATH = Path("~/.agvv/tasks.db")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PR_URL_RE = re.compile(r"/pull/([0-9]+)")
_UNSET = object()


class TaskState(str, Enum):
    """Lifecycle states for the task state machine."""

    PENDING = "pending"
    CODING = "coding"
    PR_OPEN = "pr_open"
    PR_NEEDS_WORK = "pr_needs_work"
    PR_MERGED = "pr_merged"
    PR_CLOSED = "pr_closed"
    TIMED_OUT = "timed_out"
    CLEANED = "cleaned"
    FAILED = "failed"
    BLOCKED = "blocked"


_TERMINAL_STATES = {
    TaskState.PR_MERGED,
    TaskState.PR_CLOSED,
    TaskState.TIMED_OUT,
    TaskState.CLEANED,
    TaskState.FAILED,
    TaskState.BLOCKED,
}
_ACTIVE_STATES = {TaskState.PENDING, TaskState.CODING, TaskState.PR_OPEN, TaskState.PR_NEEDS_WORK}
_RECOVERABLE_RETRY_STATES = {
    TaskState.FAILED,
    TaskState.TIMED_OUT,
    TaskState.BLOCKED,
    TaskState.PR_NEEDS_WORK,
    TaskState.CODING,
}


def _run_command(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run shell command and normalize errors."""

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
            f"Command failed: {' '.join(cmd)}\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        ) from exc


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git command."""

    return _run_command(["git", *args], cwd=cwd)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""

    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime:
    """Parse ISO timestamp into a UTC-aware datetime."""

    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_bool(value: Any, default: bool) -> bool:
    """Convert user-provided values into booleans with a default fallback."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise AgvvError(f"Invalid boolean value: {value!r}")


def _coerce_int(value: Any, label: str, default: int, min_value: int = 0) -> int:
    """Convert user-provided values into bounded integers."""

    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AgvvError(f"{label} must be an integer, got: {value!r}") from exc
    if parsed < min_value:
        raise AgvvError(f"{label} must be >= {min_value}, got: {parsed}")
    return parsed


def resolve_task_db_path(path: Path | None = None) -> Path:
    """Resolve SQLite DB path from argument/env/default."""

    if path is not None:
        return path.expanduser().resolve()
    env = os.getenv(_TASK_DB_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_TASK_DB_PATH.expanduser().resolve()


@dataclass(frozen=True)
class TaskSpec:
    """Task spec consumed by the state machine."""

    task_id: str
    project_name: str
    feature: str
    agent_cmd: str
    repo: str
    base_dir: Path
    from_branch: str = "main"
    session: str | None = None
    agent: str | None = "codex"
    ticket: str | None = None
    task_doc: Path | None = None
    params: dict[str, str] | None = None
    create_dirs: list[str] | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    pr_base: str = "main"
    branch_remote: str = "origin"
    max_retry_cycles: int = 5
    timeout_minutes: int = 240
    auto_cleanup: bool = True
    keep_branch_on_cleanup: bool = False
    commit_message: str | None = None

    def normalized_session(self) -> str:
        """Return a deterministic tmux session name for the task."""

        return self.session or f"agvv-{self.task_id}"

    def to_payload(self) -> dict[str, Any]:
        """Serialize this spec into JSON-safe primitives."""

        return {
            "task_id": self.task_id,
            "project_name": self.project_name,
            "feature": self.feature,
            "agent_cmd": self.agent_cmd,
            "repo": self.repo,
            "base_dir": str(self.base_dir),
            "from_branch": self.from_branch,
            "session": self.session,
            "agent": self.agent,
            "ticket": self.ticket,
            "task_doc": str(self.task_doc) if self.task_doc else None,
            "params": self.params or {},
            "create_dirs": self.create_dirs or [],
            "pr_title": self.pr_title,
            "pr_body": self.pr_body,
            "pr_base": self.pr_base,
            "branch_remote": self.branch_remote,
            "max_retry_cycles": self.max_retry_cycles,
            "timeout_minutes": self.timeout_minutes,
            "auto_cleanup": self.auto_cleanup,
            "keep_branch_on_cleanup": self.keep_branch_on_cleanup,
            "commit_message": self.commit_message,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TaskSpec:
        """Build a validated ``TaskSpec`` from untyped JSON/YAML payload."""

        if not isinstance(payload, dict):
            raise AgvvError("Task spec root must be an object.")

        required = ["project_name", "feature", "agent_cmd", "repo"]
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise AgvvError(f"Task spec missing required fields: {', '.join(missing)}")

        raw_id = payload.get("task_id")
        if raw_id is None:
            stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
            raw_id = f"{payload['project_name']}-{payload['feature']}-{stamp}"
        task_id = str(raw_id)
        if _TASK_ID_RE.fullmatch(task_id) is None:
            raise AgvvError(
                f"Invalid task_id '{task_id}'. Use only letters, numbers, underscores, and hyphens."
            )

        params = payload.get("params") or {}
        if not isinstance(params, dict):
            raise AgvvError("Task spec field 'params' must be an object.")

        create_dirs = payload.get("create_dirs") or []
        if not isinstance(create_dirs, list):
            raise AgvvError("Task spec field 'create_dirs' must be a list.")

        task_doc = payload.get("task_doc")
        return cls(
            task_id=task_id,
            project_name=str(payload["project_name"]),
            feature=str(payload["feature"]),
            agent_cmd=str(payload["agent_cmd"]),
            repo=str(payload["repo"]),
            base_dir=Path(str(payload.get("base_dir", "~/code"))).expanduser().resolve(),
            from_branch=str(payload.get("from_branch", "main")),
            session=(str(payload["session"]) if payload.get("session") else None),
            agent=(str(payload["agent"]) if payload.get("agent") else None),
            ticket=(str(payload["ticket"]) if payload.get("ticket") else None),
            task_doc=(Path(str(task_doc)).expanduser().resolve() if task_doc else None),
            params={str(k): str(v) for k, v in params.items()},
            create_dirs=[str(item) for item in create_dirs],
            pr_title=(str(payload["pr_title"]) if payload.get("pr_title") else None),
            pr_body=(str(payload["pr_body"]) if payload.get("pr_body") else None),
            pr_base=str(payload.get("pr_base", payload.get("from_branch", "main"))),
            branch_remote=str(payload.get("branch_remote", "origin")),
            max_retry_cycles=_coerce_int(payload.get("max_retry_cycles"), "max_retry_cycles", 5, min_value=0),
            timeout_minutes=_coerce_int(payload.get("timeout_minutes"), "timeout_minutes", 240, min_value=1),
            auto_cleanup=_coerce_bool(payload.get("auto_cleanup"), default=True),
            keep_branch_on_cleanup=_coerce_bool(payload.get("keep_branch_on_cleanup"), default=False),
            commit_message=(str(payload["commit_message"]) if payload.get("commit_message") else None),
        )


@dataclass(frozen=True)
class TaskSnapshot:
    """Runtime task row from SQLite."""

    id: str
    project_name: str
    feature: str
    state: TaskState
    session: str
    agent: str | None
    repo: str
    pr_number: int | None
    repair_cycles: int
    last_error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    spec: TaskSpec


class TaskStore:
    """SQLite-backed runtime store."""

    def __init__(self, path: Path | None = None) -> None:
        """Create a store instance and initialize schema if needed."""

        self.path = resolve_task_db_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection configured with row dictionaries."""

        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create required runtime tables and indexes."""

        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  project_name TEXT NOT NULL,
                  feature TEXT NOT NULL,
                  state TEXT NOT NULL,
                  session TEXT NOT NULL,
                  agent TEXT,
                  repo TEXT NOT NULL,
                  pr_number INTEGER,
                  repair_cycles INTEGER NOT NULL DEFAULT 0,
                  last_error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  spec_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
                CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);

                CREATE TABLE IF NOT EXISTS task_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  task_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  level TEXT NOT NULL,
                  step TEXT NOT NULL,
                  message TEXT NOT NULL,
                  meta_json TEXT,
                  FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                """
            )

    def create_task(self, spec: TaskSpec) -> TaskSnapshot:
        """Insert a new task row and return its snapshot."""

        now = _now_iso()
        session = spec.normalized_session()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO tasks (
                      id, project_name, feature, state, session, agent, repo, pr_number, repair_cycles,
                      last_error, created_at, updated_at, started_at, finished_at, spec_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        spec.task_id,
                        spec.project_name,
                        spec.feature,
                        TaskState.PENDING.value,
                        session,
                        spec.agent,
                        spec.repo,
                        now,
                        now,
                        json.dumps(spec.to_payload(), sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AgvvError(f"Task id already exists: {spec.task_id}") from exc
        self.add_event(spec.task_id, "info", "task.create", "Task created", {"state": TaskState.PENDING.value})
        return self.get_task(spec.task_id)

    def add_event(
        self,
        task_id: str,
        level: str,
        step: str,
        message: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Append a structured event record for task auditing."""

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_events (task_id, created_at, level, step, message, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, _now_iso(), level, step, message, json.dumps(meta or {}, sort_keys=True)),
            )

    def update_task(
        self,
        task_id: str,
        *,
        state: TaskState | None = None,
        pr_number: int | None | object = _UNSET,
        repair_cycles: int | object = _UNSET,
        last_error: str | None | object = _UNSET,
        started_at: str | None | object = _UNSET,
        finished_at: str | None | object = _UNSET,
    ) -> TaskSnapshot:
        """Update selected task fields and return the latest snapshot."""

        current = self.get_task(task_id)
        next_state = state or current.state
        values: dict[str, Any] = {
            "state": next_state.value,
            "updated_at": _now_iso(),
            "pr_number": current.pr_number if pr_number is _UNSET else pr_number,
            "repair_cycles": current.repair_cycles if repair_cycles is _UNSET else repair_cycles,
            "last_error": current.last_error if last_error is _UNSET else last_error,
            "started_at": current.started_at if started_at is _UNSET else started_at,
            "finished_at": current.finished_at if finished_at is _UNSET else finished_at,
        }
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET state = ?, updated_at = ?, pr_number = ?, repair_cycles = ?, last_error = ?, started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    values["state"],
                    values["updated_at"],
                    values["pr_number"],
                    values["repair_cycles"],
                    values["last_error"],
                    values["started_at"],
                    values["finished_at"],
                    task_id,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskSnapshot:
        """Fetch a task by id or raise when missing."""

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise AgvvError(f"Task not found: {task_id}")
        return self._row_to_snapshot(row)

    def list_tasks(self, *, state: TaskState | None = None) -> list[TaskSnapshot]:
        """List tasks ordered by latest update, optionally filtered by state."""

        query = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if state is not None:
            query += " WHERE state = ?"
            params = (state.value,)
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def list_active_tasks(self) -> list[TaskSnapshot]:
        """Return tasks currently in active non-terminal states."""

        placeholders = ",".join("?" for _ in _ACTIVE_STATES)
        states = tuple(state.value for state in _ACTIVE_STATES)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY updated_at ASC", states
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> TaskSnapshot:
        """Convert a raw SQLite row into ``TaskSnapshot``."""

        raw_spec = json.loads(str(row["spec_json"]))
        spec = TaskSpec.from_payload(raw_spec)
        pr_number = row["pr_number"]
        return TaskSnapshot(
            id=str(row["id"]),
            project_name=str(row["project_name"]),
            feature=str(row["feature"]),
            state=TaskState(str(row["state"])),
            session=str(row["session"]),
            agent=(str(row["agent"]) if row["agent"] is not None else None),
            repo=str(row["repo"]),
            pr_number=(int(pr_number) if pr_number is not None else None),
            repair_cycles=int(row["repair_cycles"]),
            last_error=(str(row["last_error"]) if row["last_error"] is not None else None),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=(str(row["started_at"]) if row["started_at"] is not None else None),
            finished_at=(str(row["finished_at"]) if row["finished_at"] is not None else None),
            spec=spec,
        )


def load_task_spec(path: Path) -> TaskSpec:
    """Load task spec from JSON or YAML (if PyYAML is installed)."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgvvError(f"Failed to read spec file at {path}: {exc}") from exc

    payload: Any
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AgvvError(
                "Spec file is not valid JSON. Install PyYAML to use YAML spec files."
            ) from exc
        payload = yaml.safe_load(raw)

    if not isinstance(payload, dict):
        raise AgvvError("Task spec must be an object.")
    return TaskSpec.from_payload(payload)


def _task_doc_text(spec: TaskSpec) -> str:
    """Resolve PR body text from explicit body or task document file."""

    if spec.pr_body:
        return spec.pr_body
    if spec.task_doc:
        try:
            return spec.task_doc.read_text(encoding="utf-8").strip()
        except OSError:
            return f"Task document: {spec.task_doc}"
    return f"Automated task: {spec.task_id}"


def _feature_worktree_path(task: TaskSnapshot) -> Path:
    """Return the expected feature worktree path for a task."""

    paths = layout_paths(task.project_name, task.spec.base_dir, feature=task.feature)
    if paths.feature_dir is None:
        raise RuntimeError("Internal error: feature_dir missing")
    return paths.feature_dir


def _mark_failed(store: TaskStore, task: TaskSnapshot, step: str, message: str) -> TaskSnapshot:
    """Record a failure event and move task into ``FAILED`` state."""

    store.add_event(task.id, "error", step, message)
    return store.update_task(task.id, state=TaskState.FAILED, last_error=message, finished_at=_now_iso())


def _ensure_pr_number(task: TaskSnapshot, worktree: Path) -> int:
    """Create or discover an open PR number for the task branch."""

    if task.pr_number is not None:
        return task.pr_number

    title = task.spec.pr_title or f"[agvv] {task.feature}"
    body = _task_doc_text(task.spec)
    create_error: AgvvError | None = None
    list_error: AgvvError | None = None

    try:
        create = _run_command(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                task.repo,
                "--head",
                task.feature,
                "--base",
                task.spec.pr_base,
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=worktree,
        )
        output = create.stdout.strip()
        match = _PR_URL_RE.search(output)
        if match:
            return int(match.group(1))
    except AgvvError as exc:
        create_error = exc

    try:
        listed = _run_command(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                task.repo,
                "--head",
                task.feature,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            cwd=worktree,
        ).stdout.strip()
    except AgvvError as exc:
        list_error = exc
        listed = ""

    if listed:
        return int(listed)
    if create_error is not None:
        if list_error is not None:
            raise AgvvError(
                "Failed to resolve PR number: create failed and fallback lookup failed.\n"
                f"create_error={create_error}\n"
                f"list_error={list_error}"
            ) from list_error
        raise AgvvError(
            f"Failed to resolve PR number: create failed and no existing open PR found.\ncreate_error={create_error}"
        ) from create_error
    if list_error is not None:
        raise AgvvError(f"Failed to resolve PR number from gh list: {list_error}") from list_error
    raise AgvvError("Failed to resolve PR number after creation.")


def _commit_and_push(task: TaskSnapshot, worktree: Path) -> None:
    """Commit local changes (if any), validate ahead commits, and push branch."""

    status = _git(["status", "--porcelain"], cwd=worktree).stdout.strip()
    if status:
        _git(["add", "-A"], cwd=worktree)
        message = task.spec.commit_message or f"feat({task.feature}): implement {task.id}"
        _git(["commit", "-m", message], cwd=worktree)

    ahead = _git(["rev-list", "--count", f"{task.spec.pr_base}..{task.feature}"], cwd=worktree).stdout.strip()
    if int(ahead or "0") <= 0:
        raise AgvvError(
            f"Task {task.id} produced no commits ahead of base branch '{task.spec.pr_base}'."
        )
    _git(["push", "-u", task.spec.branch_remote, task.feature], cwd=worktree)


def _launch_coding_session(store: TaskStore, task: TaskSnapshot, *, fresh_setup: bool) -> TaskSnapshot:
    """Ensure workspace exists and start a tmux coding session for the task."""

    if tmux_session_exists(task.session):
        raise AgvvError(f"tmux session already exists: {task.session}")

    try:
        if fresh_setup:
            start_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                from_branch=task.spec.from_branch,
                agent=task.agent,
                task_id=task.id,
                ticket=task.spec.ticket,
                params={
                    **(task.spec.params or {}),
                    "task_doc": str(task.spec.task_doc) if task.spec.task_doc else "",
                },
                create_dirs=task.spec.create_dirs or [],
            )
        worktree = _feature_worktree_path(task)
        if not worktree.exists():
            raise AgvvError(f"Feature worktree not found: {worktree}")
        tmux_new_session(task.session, cwd=worktree, command=task.spec.agent_cmd)
    except Exception as exc:
        message = f"Failed to launch coding session: {exc}"
        return _mark_failed(store, task, "task.launch", message)

    store.add_event(task.id, "info", "task.launch", "Coding session started", {"session": task.session})
    return store.update_task(
        task.id,
        state=TaskState.CODING,
        started_at=(task.started_at or _now_iso()),
        finished_at=None,
        last_error=None,
    )


def run_task_from_spec(spec_path: Path, db_path: Path | None = None) -> TaskSnapshot:
    """Create a task from spec and start the coding session."""

    spec = load_task_spec(spec_path)
    store = TaskStore(db_path)
    created = store.create_task(spec)
    return _launch_coding_session(store, created, fresh_setup=True)


def retry_task(task_id: str, db_path: Path | None = None, session: str | None = None) -> TaskSnapshot:
    """Retry task from failed/blocked/needs-work/timed-out states."""

    store = TaskStore(db_path)
    task = store.get_task(task_id)
    if task.state not in _RECOVERABLE_RETRY_STATES:
        raise AgvvError(f"Cannot retry task in state: {task.state.value}")
    if task.state == TaskState.CODING and tmux_session_exists(task.session):
        raise AgvvError(f"Task is already running in session: {task.session}")

    if session and session != task.session:
        store.add_event(task.id, "info", "task.retry", "Session override requested", {"session": session})
        with store._connect() as conn:
            conn.execute("UPDATE tasks SET session = ?, updated_at = ? WHERE id = ?", (session, _now_iso(), task.id))
        task = store.get_task(task.id)

    worktree = _feature_worktree_path(task)
    return _launch_coding_session(store, task, fresh_setup=not worktree.exists())


def _cleanup_force(task: TaskSnapshot) -> None:
    """Force-remove worktree and optionally delete local branch."""

    paths = layout_paths(task.project_name, task.spec.base_dir, feature=task.feature)
    if paths.feature_dir is None:
        raise RuntimeError("Internal error: feature_dir missing")
    repo_dir = paths.repo_dir
    if not repo_dir.exists():
        return
    if paths.feature_dir.exists():
        _run_command(["git", "-C", str(repo_dir), "worktree", "remove", str(paths.feature_dir), "--force"])
    exists = subprocess.run(
        ["git", "-C", str(repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{task.feature}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if exists.returncode == 0 and not task.spec.keep_branch_on_cleanup:
        _run_command(["git", "-C", str(repo_dir), "branch", "-D", task.feature])


def cleanup_task(task_id: str, db_path: Path | None = None, force: bool = False) -> TaskSnapshot:
    """Cleanup task resources and mark task as cleaned."""

    store = TaskStore(db_path)
    task = store.get_task(task_id)

    try:
        if tmux_session_exists(task.session):
            tmux_kill_session(task.session)

        if force:
            _cleanup_force(task)
        else:
            cleanup_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                delete_branch=not task.spec.keep_branch_on_cleanup,
            )
    except Exception as exc:
        return _mark_failed(store, task, "task.cleanup", f"Cleanup failed: {exc}")

    store.add_event(task.id, "info", "task.cleanup", "Task resources cleaned")
    return store.update_task(task.id, state=TaskState.CLEANED, finished_at=_now_iso(), last_error=None)


def _handle_coding_completion(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Finalize a finished coding session by pushing commits and opening PR."""

    if tmux_session_exists(task.session):
        return task

    worktree = _feature_worktree_path(task)
    if not worktree.exists():
        return _mark_failed(store, task, "coding.verify", f"Worktree missing: {worktree}")

    try:
        _commit_and_push(task, worktree)
        pr_number = _ensure_pr_number(task, worktree)
    except Exception as exc:
        return _mark_failed(store, task, "coding.finalize", f"Finalize coding failed: {exc}")

    store.add_event(task.id, "info", "pr.open", "PR opened/confirmed", {"pr_number": pr_number})
    return store.update_task(task.id, state=TaskState.PR_OPEN, pr_number=pr_number, last_error=None)


def _handle_pr_cycle(store: TaskStore, task: TaskSnapshot) -> TaskSnapshot:
    """Advance PR state, including timeout, merge/close handling, and retry loops."""

    if task.pr_number is None:
        return _mark_failed(store, task, "pr.check", "PR number missing for PR cycle.")

    elapsed = datetime.now(tz=timezone.utc) - _parse_iso(task.created_at)
    if elapsed > timedelta(minutes=task.spec.timeout_minutes):
        timed = store.update_task(task.id, state=TaskState.TIMED_OUT, finished_at=_now_iso(), last_error="task_timeout")
        store.add_event(task.id, "error", "task.timeout", "Task timed out", {"timeout_minutes": task.spec.timeout_minutes})
        if task.spec.auto_cleanup:
            return cleanup_task(task.id, db_path=store.path, force=False)
        return timed

    try:
        result = check_pr_status(task.repo, task.pr_number)
    except Exception as exc:
        return _mark_failed(store, task, "pr.check", f"PR status check failed: {exc}")

    if result.status == "waiting":
        return store.update_task(task.id, state=TaskState.PR_OPEN)

    if result.status == "done":
        merged = store.update_task(task.id, state=TaskState.PR_MERGED, finished_at=_now_iso(), last_error=None)
        store.add_event(task.id, "info", "pr.merged", "PR merged")
        if task.spec.auto_cleanup:
            return cleanup_task(task.id, db_path=store.path, force=False)
        return merged

    if result.status == "closed":
        closed = store.update_task(task.id, state=TaskState.PR_CLOSED, finished_at=_now_iso(), last_error=None)
        store.add_event(task.id, "info", "pr.closed", "PR closed")
        if task.spec.auto_cleanup:
            return cleanup_task(task.id, db_path=store.path, force=False)
        return closed

    feedback = summarize_pr_feedback(task.repo, task.pr_number)
    if task.repair_cycles >= task.spec.max_retry_cycles:
        return _mark_failed(
            store,
            task,
            "pr.retry",
            (
                f"Reached max retry cycles ({task.spec.max_retry_cycles}). "
                f"Actionable comments: {len(feedback.actionable)}"
            ),
        )

    worktree = _feature_worktree_path(task)
    if not worktree.exists():
        return _mark_failed(store, task, "pr.retry", f"Worktree missing: {worktree}")

    feedback_path = worktree / ".agvv" / "feedback.txt"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"PR feedback cycle for task={task.id} pr={task.pr_number}",
        "",
        "Actionable:",
        *[f"- {item}" for item in feedback.actionable],
        "",
        "Skipped:",
        *[f"- {item}" for item in feedback.skipped[:10]],
    ]
    feedback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if tmux_session_exists(task.session):
        return store.update_task(task.id, state=TaskState.CODING)

    try:
        tmux_new_session(task.session, cwd=worktree, command=task.spec.agent_cmd)
    except Exception as exc:
        return _mark_failed(store, task, "pr.retry", f"Failed to relaunch coding session: {exc}")

    store.add_event(
        task.id,
        "info",
        "pr.retry",
        "Feedback received; coding session relaunched",
        {"cycle": task.repair_cycles + 1, "feedback_file": str(feedback_path)},
    )
    return store.update_task(
        task.id,
        state=TaskState.CODING,
        repair_cycles=task.repair_cycles + 1,
        last_error=None,
    )


def reconcile_task(task_id: str, db_path: Path | None = None) -> TaskSnapshot:
    """Reconcile one task based on its current runtime state."""

    store = TaskStore(db_path)
    task = store.get_task(task_id)
    if task.state in _TERMINAL_STATES:
        return task

    if task.state == TaskState.PENDING:
        return _launch_coding_session(store, task, fresh_setup=True)

    if task.state == TaskState.CODING:
        return _handle_coding_completion(store, task)

    if task.state in {TaskState.PR_OPEN, TaskState.PR_NEEDS_WORK}:
        return _handle_pr_cycle(store, task)

    return task


def daemon_run_once(db_path: Path | None = None) -> list[TaskSnapshot]:
    """Reconcile all active tasks once."""

    store = TaskStore(db_path)
    results: list[TaskSnapshot] = []
    for task in store.list_active_tasks():
        results.append(reconcile_task(task.id, db_path=store.path))
    return results


def daemon_run_loop(
    db_path: Path | None = None,
    interval_seconds: int = 30,
    max_loops: int | None = None,
) -> int:
    """Continuously reconcile tasks until interrupted or max_loops reached."""

    if interval_seconds <= 0:
        raise AgvvError("interval_seconds must be > 0")

    loops = 0
    while True:
        daemon_run_once(db_path)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return loops
        time.sleep(interval_seconds)


def list_task_statuses(db_path: Path | None = None, state: TaskState | None = None) -> list[TaskSnapshot]:
    """List tasks ordered by latest update."""

    store = TaskStore(db_path)
    return store.list_tasks(state=state)
