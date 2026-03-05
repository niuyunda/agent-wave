from __future__ import annotations

import sqlite3
from pathlib import Path

from agvv.runtime.models import TaskSpec
from agvv.runtime.store import TaskStore


def test_task_store_connections_are_closed_after_operation(
    monkeypatch, tmp_path: Path
) -> None:
    opened = {"count": 0}
    closed = {"count": 0}
    original_connect = sqlite3.connect

    class _TrackedConnection(sqlite3.Connection):
        def close(self) -> None:
            closed["count"] += 1
            super().close()

    def _tracked_connect(*args, **kwargs):
        kwargs.setdefault("factory", _TrackedConnection)
        opened["count"] += 1
        return original_connect(*args, **kwargs)

    monkeypatch.setattr("agvv.runtime.store.sqlite3.connect", _tracked_connect)

    store = TaskStore(tmp_path / "tasks.db")
    spec = TaskSpec(
        task_id="tracked_conn_task",
        project_name="demo",
        feature="feat_tracked_conn",
        agent_cmd="echo run",
        repo="owner/repo",
        base_dir=tmp_path,
    )
    store.create_task(spec)

    # All opened sqlite connections from this flow must be closed.
    assert opened["count"] > 0
    assert closed["count"] == opened["count"]
