"""Typer command-line interface for Agent Wave task orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from agvv.core import AgvvError
from agvv.tasking import (
    TaskState,
    cleanup_task,
    daemon_run_loop,
    daemon_run_once,
    list_task_statuses,
    retry_task,
    run_task_from_spec,
)

app = typer.Typer(help="Agent Wave task orchestration CLI.")
task_app = typer.Typer(help="Task state-machine orchestration operations.")
daemon_app = typer.Typer(help="Task monitor daemon operations.")

app.add_typer(task_app, name="task")
app.add_typer(daemon_app, name="daemon")


def _exit_with_agvv_error(exc: AgvvError) -> None:
    """Render operational errors to stderr and exit non-zero."""

    typer.secho(str(exc), err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1) from exc


def _resolve_optional_path(path: str | None) -> Path | None:
    """Resolve an optional path string to an absolute ``Path``."""

    return Path(path).expanduser().resolve() if path else None


def _parse_task_state(value: str | None) -> TaskState | None:
    """Parse optional task state value."""

    if value is None:
        return None
    try:
        return TaskState(value)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TaskState)
        raise typer.BadParameter(f"Unsupported --state value '{value}'. Use one of: {supported}") from exc


@task_app.command("run")
def task_run(
    spec: Annotated[str, typer.Option("--spec", help="Path to task spec JSON/YAML.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
) -> None:
    """Create and launch a task from spec."""

    try:
        task = run_task_from_spec(
            spec_path=Path(spec).expanduser().resolve(),
            db_path=_resolve_optional_path(db_path),
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(
        f"Task started: {task.id}\tstate={task.state.value}\t"
        f"target={task.project_name}/{task.feature}\tsession={task.session}"
    )


@task_app.command("status")
def task_status(
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help="Filter by task id.")] = None,
    state: Annotated[str | None, typer.Option("--state", help="Filter by state value.")] = None,
) -> None:
    """List task state-machine runtime status."""

    parsed_state = _parse_task_state(state)
    try:
        tasks = list_task_statuses(db_path=_resolve_optional_path(db_path), state=parsed_state)
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    if task_id is not None:
        tasks = [item for item in tasks if item.id == task_id]

    if not tasks:
        typer.echo("No tasks found.")
        return

    for task in tasks:
        pr_value = str(task.pr_number) if task.pr_number is not None else "-"
        error_value = task.last_error or "-"
        typer.echo(
            f"{task.id}\t{task.state.value}\t{task.project_name}/{task.feature}\t"
            f"session={task.session}\tpr={pr_value}\tcycles={task.repair_cycles}\t"
            f"error={error_value}\tupdated={task.updated_at}"
        )


@task_app.command("retry")
def task_retry(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to retry.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    session: Annotated[str | None, typer.Option("--session", help="Override tmux session.")] = None,
) -> None:
    """Retry a task by launching a new coding session."""

    try:
        task = retry_task(task_id=task_id, db_path=_resolve_optional_path(db_path), session=session)
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(f"Task retried: {task.id}\tstate={task.state.value}\tsession={task.session}")


@task_app.command("cleanup")
def task_cleanup(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to cleanup.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Force cleanup (discard local changes).")] = False,
) -> None:
    """Cleanup task resources and mark task as cleaned."""

    try:
        task = cleanup_task(task_id=task_id, db_path=_resolve_optional_path(db_path), force=force)
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(f"Task cleaned: {task.id}\tstate={task.state.value}")


@daemon_app.command("run")
def daemon_run(
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    interval_seconds: Annotated[int, typer.Option("--interval-seconds", help="Loop interval in seconds.")] = 30,
    once: Annotated[bool, typer.Option("--once", help="Run one reconcile pass and exit.")] = False,
    max_loops: Annotated[int | None, typer.Option("--max-loops", help="Optional max loops before exit.")] = None,
) -> None:
    """Run task monitor daemon loop."""

    resolved_db = _resolve_optional_path(db_path)
    try:
        if once:
            results = daemon_run_once(db_path=resolved_db)
            typer.echo(f"daemon pass complete: reconciled={len(results)}")
            for task in results:
                typer.echo(f"{task.id}\t{task.state.value}\tupdated={task.updated_at}")
            return
        loops = daemon_run_loop(
            db_path=resolved_db,
            interval_seconds=interval_seconds,
            max_loops=max_loops,
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)
    except KeyboardInterrupt:
        typer.echo("daemon interrupted")
        raise typer.Exit(code=130) from None

    typer.echo(f"daemon exited after loops={loops}")


if __name__ == "__main__":
    app()
