"""task subcommand."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import task
from agvv.daemon.server import get_daemon_status, start_daemon
from agvv.utils.format import print_error, print_json, print_success

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


def _list_tasks(project: str | None) -> None:
    """List tasks with latest run snapshot."""
    if project:
        projects = [Path(project).resolve()]
    else:
        projects = [Path(e.path) for e in proj_mod.list_projects()]

    all_tasks = []
    for pp in projects:
        for t in task.list_tasks(pp):
            t["project"] = str(pp)
            all_tasks.append(t)

    print_json(all_tasks)


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_daemon_running() -> tuple[bool, int | None]:
    if _truthy_env("AGVV_SKIP_DAEMON_AUTOSTART"):
        return False, None

    info = get_daemon_status()
    if info["running"]:
        return False, info.get("pid")

    pid = start_daemon()
    return True, pid


@app.callback()
def tasks(
    ctx: typer.Context,
    project: str = typer.Option(None, "--project", help="Filter to one project path (omit for all registered projects)"),
) -> None:
    """Create, inspect, and merge tasks."""
    if ctx.invoked_subcommand is None:
        _list_tasks(project)


@app.command("list")
def list_cmd(
    project: str = typer.Option(None, "--project", help="Filter to one project path (omit for all registered projects)"),
) -> None:
    """Alias for `agvv tasks`."""
    _list_tasks(project)


@app.command()
def add(
    project: str = typer.Option(..., "--project", help="Target repository path"),
    file: str = typer.Option(
        ...,
        "--file",
        help="Task markdown; YAML front matter must include `name`",
    ),
    create_project: bool = typer.Option(
        False,
        "--create-project",
        help="Create --project directory if it does not exist",
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help="Agent name passed to acpx for daemon auto-run (for example: codex, claude)",
    ),
) -> None:
    """Create a task record from markdown in a project.

    Source front matter is copied into `.agvv/tasks/<name>/task.md` except that
    missing `status` defaults to pending and missing `created_at` to today.
    Example layout (optional): see ``docs/task-template.md`` in the agvv repo.
    """
    try:
        project_path = Path(project).resolve()
        if create_project and not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)
        selected_agent = agent.strip() if agent is not None else None
        proj_mod.ensure_project(project_path)
        daemon_started, daemon_pid = _ensure_daemon_running()
        name = task.add_task(project_path, Path(file), agent=selected_agent)
        task.mark_task_auto_managed(project_path, name, enabled=True)
        feedback_message = "Task accepted. Daemon will auto-run implement."
        if selected_agent:
            feedback_message = (
                f"Task accepted. Daemon will auto-run implement with agent '{selected_agent}'."
            )
        task.set_task_feedback(
            project_path,
            name,
            "queued",
            feedback_message,
        )
        print_success(
            "Task created",
            project=str(project_path),
            task=name,
            agent=selected_agent,
            orchestration="auto",
            daemon_started=daemon_started,
            daemon_pid=daemon_pid,
        )
    except (ValueError, RuntimeError) as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def show(
    task_name: str = typer.Argument(..., help="Task name from task front matter"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Show full task state, body, and run history."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        info = task.show_task(pp, task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    print_json(info)


@app.command()
def merge(
    task_name: str = typer.Argument(..., help="Task to merge"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Merge `agvv/<task>` into main and archive on success."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        commit = task.merge_task(pp, task_name)
        print_success("Task merged", project=str(pp), task=task_name, commit=commit)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
