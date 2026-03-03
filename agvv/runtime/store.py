"""SQLite-backed runtime storage for task orchestration."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from agvv.shared.errors import AgvvError
from agvv.runtime.models import ACTIVE_STATES, TaskSpec, TaskState

_TASK_DB_ENV_VAR = "AGVV_DB_PATH"
_DEFAULT_TASK_DB_PATH = Path("~/.agvv/tasks.db")
_UNSET = object()


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""

    return datetime.now(tz=timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime:
    """Parse ISO timestamp into a UTC-aware datetime."""

    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_task_db_path(path: Path | None = None) -> Path:
    """Resolve SQLite DB path from argument/env/default."""

    if path is not None:
        return path.expanduser().resolve()
    env = os.getenv(_TASK_DB_ENV_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_TASK_DB_PATH.expanduser().resolve()


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

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a transaction-scoped connection and always close it."""

        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create required runtime tables and indexes."""

        with self._connection() as conn:
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

                CREATE TABLE IF NOT EXISTS task_reconcile_locks (
                  task_id TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL,
                  acquired_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );
                """
            )

    def create_task(self, spec: TaskSpec) -> TaskSnapshot:
        """Insert a new task row and return its snapshot."""

        now = now_iso()
        session = spec.normalized_session()
        with self._connection() as conn:
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

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO task_events (task_id, created_at, level, step, message, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, now_iso(), level, step, message, json.dumps(meta or {}, sort_keys=True)),
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
            "updated_at": now_iso(),
            "pr_number": current.pr_number if pr_number is _UNSET else pr_number,
            "repair_cycles": current.repair_cycles if repair_cycles is _UNSET else repair_cycles,
            "last_error": current.last_error if last_error is _UNSET else last_error,
            "started_at": current.started_at if started_at is _UNSET else started_at,
            "finished_at": current.finished_at if finished_at is _UNSET else finished_at,
        }
        with self._connection() as conn:
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

        with self._connection() as conn:
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
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def list_active_tasks(self) -> list[TaskSnapshot]:
        """Return tasks currently in active non-terminal states."""

        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        states = tuple(state.value for state in ACTIVE_STATES)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY updated_at ASC", states
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def update_task_session(self, task_id: str, session: str) -> TaskSnapshot:
        """Update tmux session name for a task and return latest snapshot."""

        self.get_task(task_id)
        with self._connection() as conn:
            conn.execute(
                "UPDATE tasks SET session = ?, updated_at = ? WHERE id = ?",
                (session, now_iso(), task_id),
            )
        return self.get_task(task_id)

    def try_acquire_reconcile_lock(self, task_id: str, *, owner_id: str, ttl_seconds: int = 300) -> bool:
        """Try to acquire a task reconcile lock for one owner."""

        if ttl_seconds <= 0:
            raise AgvvError("ttl_seconds must be > 0")

        acquired_at = now_iso()
        expires_at = (datetime.now(tz=timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        with self._connection() as conn:
            conn.execute("DELETE FROM task_reconcile_locks WHERE expires_at <= ?", (acquired_at,))
            try:
                conn.execute(
                    """
                    INSERT INTO task_reconcile_locks (task_id, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, owner_id, acquired_at, expires_at),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def release_reconcile_lock(self, task_id: str, *, owner_id: str) -> None:
        """Release a task reconcile lock owned by ``owner_id``."""

        with self._connection() as conn:
            conn.execute(
                "DELETE FROM task_reconcile_locks WHERE task_id = ? AND owner_id = ?",
                (task_id, owner_id),
            )

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
