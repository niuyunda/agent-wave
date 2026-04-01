"""task subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import task
from agvv.utils.format import print_error, print_json, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def add(
    project: str = typer.Option(..., "--project", help="Target repository path"),
    file: str = typer.Option(
        ...,
        "--file",
        help="Task markdown; YAML front matter must include `name`",
    ),
) -> None:
    """Create a task record from markdown in a project.

    Source front matter is copied into `.agvv/tasks/<name>/task.md` except that
    missing `status` defaults to pending and missing `created_at` to today.
    Example layout (optional): see ``docs/task-template.md`` in the agvv repo.
    """
    try:
        project_path = Path(project).resolve()
        name = task.add_task(project_path, Path(file))
        print_success("Task created", project=str(project_path), task=name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    project: str = typer.Option(None, "--project", help="Filter to one project path (omit for all registered projects)"),
) -> None:
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
