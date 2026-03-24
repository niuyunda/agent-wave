"""Typer command-line interface for Agent Wave task orchestration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from agvv.runtime.models import TaskState
from agvv.runtime.core import (
    cleanup_task,
    list_task_statuses,
    retry_task,
    run_task_from_spec,
)
from agvv.runtime.dispatcher import daemon_run_loop, daemon_run_once
from agvv.shared.errors import AgvvError

app = typer.Typer(help="Agent Wave task orchestration CLI.")
task_app = typer.Typer(help="Task state-machine orchestration operations.")
daemon_app = typer.Typer(help="Task monitor daemon operations.")

app.add_typer(task_app, name="task")
app.add_typer(daemon_app, name="daemon")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _exit_error(exc: AgvvError) -> NoReturn:
    """Print a domain error and exit the CLI with status 1."""
    typer.secho(str(exc), err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1) from exc


def _resolve_path(path: str | None) -> Path | None:
    """Expand and resolve a user-supplied path string when present."""
    return Path(path).expanduser().resolve() if path else None


def _parse_state(value: str | None) -> TaskState | None:
    """Parse CLI state text into TaskState with a friendly validation error."""
    if value is None:
        return None
    try:
        return TaskState(value)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TaskState)
        raise typer.BadParameter(
            f"Unsupported --state value '{value}'. Use one of: {supported}"
        ) from exc


# ---------------------------------------------------------------------------
# task run
# ---------------------------------------------------------------------------


@task_app.command("run")
def task_run(
    spec: Annotated[str, typer.Option("--spec", help="Path to task.md spec file.")],
    db_path: Annotated[
        str | None, typer.Option("--db-path", help="Path to SQLite task DB.")
    ] = None,
    agent: Annotated[
        str | None, typer.Option("--agent", help="Override agent provider.")
    ] = None,
    project_dir: Annotated[
        str | None,
        typer.Option(
            "--project-dir",
            help="Path to an existing local git project. If set, task run auto-adopts it before launch.",
        ),
    ] = None,
) -> None:
    """Create and launch a task from spec."""
    try:
        task = run_task_from_spec(
            spec_path=Path(spec).expanduser().resolve(),
            db_path=_resolve_path(db_path),
            agent_provider=agent,
            project_dir=_resolve_path(project_dir),
        )
    except AgvvError as exc:
        _exit_error(exc)

    typer.echo(
        f"Task started: {task.id}\tstate={task.state.value}\t"
        f"target={task.project_name}/{task.feature}\tsession={task.session}"
    )


# ---------------------------------------------------------------------------
# task status
# ---------------------------------------------------------------------------


@task_app.command("status")
def task_status(
    db_path: Annotated[
        str | None, typer.Option("--db-path", help="Path to SQLite task DB.")
    ] = None,
    task_id: Annotated[
        str | None, typer.Option("--task-id", help="Filter by task id.")
    ] = None,
    state: Annotated[
        str | None, typer.Option("--state", help="Filter by state value.")
    ] = None,
) -> None:
    """List task state-machine runtime status."""
    try:
        tasks = list_task_statuses(
            db_path=_resolve_path(db_path), state=_parse_state(state)
        )
    except AgvvError as exc:
        _exit_error(exc)

    if task_id is not None:
        tasks = [t for t in tasks if t.id == task_id]

    if not tasks:
        typer.echo("No tasks found.")
        return

    for task in tasks:
        if task.last_error is None:
            error_value = "-"
        else:
            normalized = re.sub(r"[\r\n\t]+", " ", task.last_error)
            error_value = re.sub(r"\s+", " ", normalized).strip() or "-"
        typer.echo(
            f"{task.id}\t{task.state.value}\t{task.project_name}/{task.feature}\t"
            f"session={task.session}\terror={error_value}\tupdated={task.updated_at}"
        )


# ---------------------------------------------------------------------------
# task retry
# ---------------------------------------------------------------------------


@task_app.command("retry")
def task_retry(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to retry.")],
    db_path: Annotated[
        str | None, typer.Option("--db-path", help="Path to SQLite task DB.")
    ] = None,
    session: Annotated[
        str | None, typer.Option("--session", help="Override tmux session.")
    ] = None,
    force_restart: Annotated[
        bool,
        typer.Option(
            "--force-restart",
            help="Kill existing tmux session when task is currently running, then relaunch.",
        ),
    ] = False,
) -> None:
    """Retry a task by launching a new coding session."""
    try:
        task = retry_task(
            task_id=task_id,
            db_path=_resolve_path(db_path),
            session=session,
            force_restart=force_restart,
        )
    except AgvvError as exc:
        _exit_error(exc)

    typer.echo(
        f"Task retried: {task.id}\tstate={task.state.value}\tsession={task.session}"
    )


# ---------------------------------------------------------------------------
# task cleanup
# ---------------------------------------------------------------------------


@task_app.command("cleanup")
def task_cleanup(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to cleanup.")],
    db_path: Annotated[
        str | None, typer.Option("--db-path", help="Path to SQLite task DB.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Force cleanup (discard local changes).")
    ] = False,
) -> None:
    """Cleanup task resources and mark task as cleaned."""
    try:
        task = cleanup_task(
            task_id=task_id, db_path=_resolve_path(db_path), force=force
        )
    except AgvvError as exc:
        _exit_error(exc)

    typer.echo(f"Task cleaned: {task.id}\tstate={task.state.value}")


# ---------------------------------------------------------------------------
# daemon run
# ---------------------------------------------------------------------------


@daemon_app.command("run")
def daemon_run(
    db_path: Annotated[
        str | None, typer.Option("--db-path", help="Path to SQLite task DB.")
    ] = None,
    interval_seconds: Annotated[
        int, typer.Option("--interval-seconds", help="Loop interval in seconds.")
    ] = 30,
    once: Annotated[
        bool, typer.Option("--once", help="Run one reconcile pass and exit.")
    ] = False,
    max_loops: Annotated[
        int | None, typer.Option("--max-loops", help="Optional max loops before exit.")
    ] = None,
    max_workers: Annotated[
        int, typer.Option("--max-workers", help="Max worker tasks per daemon pass.")
    ] = 1,
) -> None:
    """Run task monitor daemon loop."""
    resolved_db = _resolve_path(db_path)
    try:
        if once:
            results = daemon_run_once(db_path=resolved_db, max_workers=max_workers)
            typer.echo(f"daemon pass complete: reconciled={len(results)}")
            for task in results:
                typer.echo(f"{task.id}\t{task.state.value}\tupdated={task.updated_at}")
        else:
            loops = daemon_run_loop(
                db_path=resolved_db,
                interval_seconds=interval_seconds,
                max_loops=max_loops,
                max_workers=max_workers,
            )
            typer.echo(f"daemon exited after loops={loops}")
    except AgvvError as exc:
        _exit_error(exc)
    except KeyboardInterrupt:
        typer.echo("daemon interrupted")
        raise typer.Exit(code=130) from None


if __name__ == "__main__":
    app()
