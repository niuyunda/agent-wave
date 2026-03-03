"""Daemon command handlers extracted from CLI presentation wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from agvv.commands.contracts import DaemonRunLoopFn, DaemonRunOnceFn

def execute_daemon_run(
    *,
    db_path: str | None,
    interval_seconds: int,
    once: bool,
    max_loops: int | None,
    max_workers: int,
    daemon_run_once: DaemonRunOnceFn,
    daemon_run_loop: DaemonRunLoopFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> list[str]:
    """Run daemon once/loop and return rendered output lines."""

    resolved_db = resolve_optional_path(db_path)
    if once:
        results = daemon_run_once(db_path=resolved_db, max_workers=max_workers)
        lines = [f"daemon pass complete: reconciled={len(results)}"]
        lines.extend(f"{task.id}\t{task.state.value}\tupdated={task.updated_at}" for task in results)
        return lines

    loops = daemon_run_loop(
        db_path=resolved_db,
        interval_seconds=interval_seconds,
        max_loops=max_loops,
        max_workers=max_workers,
    )
    return [f"daemon exited after loops={loops}"]
