"""Typer command-line interface for Agent Wave task orchestration."""

from __future__ import annotations

from typing import Annotated

import typer

from agvv.commands.common import exit_with_agvv_error, parse_task_state, resolve_optional_path
from agvv.commands.daemon import execute_daemon_run
from agvv.commands.project import execute_project_adopt, execute_project_init
from agvv.commands.task import (
    execute_task_cleanup,
    execute_task_retry,
    execute_task_run,
    execute_task_status,
)
from agvv.orchestration import adopt_project, init_project
from agvv.runtime import (
    cleanup_task,
    daemon_run_loop,
    daemon_run_once,
    list_task_statuses,
    retry_task,
    run_task_from_spec,
)
from agvv.shared.errors import AgvvError

app = typer.Typer(help="Agent Wave task orchestration CLI.")
task_app = typer.Typer(help="Task state-machine orchestration operations.")
daemon_app = typer.Typer(help="Task monitor daemon operations.")
project_app = typer.Typer(help="Project repository layout operations.")

app.add_typer(task_app, name="task")
app.add_typer(daemon_app, name="daemon")
app.add_typer(project_app, name="project")


@task_app.command("run")
def task_run(
    spec: Annotated[str, typer.Option("--spec", help="Path to task spec JSON/YAML.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Override agent provider.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override agent model.")] = None,
) -> None:
    """Create and launch a task from spec."""

    try:
        line = execute_task_run(
            spec=spec,
            db_path=db_path,
            agent=agent,
            model=model,
            run_task_from_spec=run_task_from_spec,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    typer.echo(line)


@task_app.command("status")
def task_status(
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help="Filter by task id.")] = None,
    state: Annotated[str | None, typer.Option("--state", help="Filter by state value.")] = None,
) -> None:
    """List task state-machine runtime status."""

    try:
        lines = execute_task_status(
            db_path=db_path,
            task_id=task_id,
            state=state,
            list_task_statuses=list_task_statuses,
            resolve_optional_path=resolve_optional_path,
            parse_task_state=parse_task_state,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    for line in lines:
        typer.echo(line)


@task_app.command("retry")
def task_retry(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to retry.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    session: Annotated[str | None, typer.Option("--session", help="Override tmux session.")] = None,
) -> None:
    """Retry a task by launching a new coding session."""

    try:
        line = execute_task_retry(
            task_id=task_id,
            db_path=db_path,
            session=session,
            retry_task=retry_task,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    typer.echo(line)


@task_app.command("cleanup")
def task_cleanup(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id to cleanup.")],
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Force cleanup (discard local changes).")] = False,
) -> None:
    """Cleanup task resources and mark task as cleaned."""

    try:
        line = execute_task_cleanup(
            task_id=task_id,
            db_path=db_path,
            force=force,
            cleanup_task=cleanup_task,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    typer.echo(line)


@daemon_app.command("run")
def daemon_run(
    db_path: Annotated[str | None, typer.Option("--db-path", help="Path to SQLite task DB.")] = None,
    interval_seconds: Annotated[int, typer.Option("--interval-seconds", help="Loop interval in seconds.")] = 30,
    once: Annotated[bool, typer.Option("--once", help="Run one reconcile pass and exit.")] = False,
    max_loops: Annotated[int | None, typer.Option("--max-loops", help="Optional max loops before exit.")] = None,
    max_workers: Annotated[int, typer.Option("--max-workers", help="Max worker tasks per daemon pass.")] = 1,
) -> None:
    """Run task monitor daemon loop."""

    try:
        lines = execute_daemon_run(
            db_path=db_path,
            interval_seconds=interval_seconds,
            once=once,
            max_loops=max_loops,
            max_workers=max_workers,
            daemon_run_once=daemon_run_once,
            daemon_run_loop=daemon_run_loop,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)
    except KeyboardInterrupt:
        typer.echo("daemon interrupted")
        raise typer.Exit(code=130) from None

    for line in lines:
        typer.echo(line)


@project_app.command("init")
def project_init(
    project_name: Annotated[str, typer.Argument(help="Project name for the managed layout.")],
    base_dir: Annotated[
        str | None,
        typer.Option("--base-dir", help="Base directory where project layout is created."),
    ] = None,
) -> None:
    """Initialize a project as bare repository plus ``main`` worktree."""

    try:
        line = execute_project_init(
            project_name=project_name,
            base_dir=base_dir,
            init_project=init_project,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    typer.echo(line)


@project_app.command("adopt")
def project_adopt(
    project_name: Annotated[str, typer.Argument(help="Project name for the managed layout.")],
    existing_repo: Annotated[
        str,
        typer.Option("--existing-repo", help="Path to an existing non-bare git repository."),
    ],
    base_dir: Annotated[
        str | None,
        typer.Option("--base-dir", help="Base directory where project layout is created."),
    ] = None,
) -> None:
    """Adopt an existing repository into the managed project layout."""

    try:
        line = execute_project_adopt(
            existing_repo=existing_repo,
            project_name=project_name,
            base_dir=base_dir,
            adopt_project=adopt_project,
            resolve_optional_path=resolve_optional_path,
        )
    except AgvvError as exc:
        exit_with_agvv_error(exc)

    typer.echo(line)


if __name__ == "__main__":
    app()
