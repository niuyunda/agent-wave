"""task subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import task
from agvv.utils.format import print_error, print_info, print_json, print_success, print_table

app = typer.Typer(no_args_is_help=True)


@app.command()
def add(
    project: str = typer.Option(..., "--project", help="Project path"),
    file: str = typer.Option(..., "--file", help="Path to task.md file"),
) -> None:
    """Register a task from a task.md file."""
    try:
        name = task.add_task(Path(project).resolve(), Path(file))
        print_success(f"Task created: {name}")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    project: str = typer.Option(None, "--project", help="Project path (all if omitted)"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all tasks."""
    if project:
        projects = [Path(project).resolve()]
    else:
        projects = [Path(e.path) for e in proj_mod.list_projects()]

    if not projects:
        print_error("No projects registered")
        raise typer.Exit(1)

    all_tasks = []
    for pp in projects:
        for t in task.list_tasks(pp):
            t["project"] = str(pp)
            all_tasks.append(t)

    if as_json:
        print_json(all_tasks)
        return

    if not all_tasks:
        print_info("No tasks found")
        return

    columns = ["TASK", "STATUS", "RUN#", "PURPOSE", "AGENT", "LAST EVENT"]
    rows = []
    for t in all_tasks:
        rows.append([
            t.get("name", "?"),
            t.get("status", "-"),
            str(t.get("run_number", 0) or "-"),
            t.get("last_purpose") or "-",
            t.get("last_agent") or "-",
            t.get("last_event") or "-",
        ])
    print_table(columns, rows)


@app.command()
def show(
    task_name: str = typer.Argument(..., help="Task name"),
    project: str = typer.Option(None, "--project", help="Project path"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show detailed task info including run history."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        info = task.show_task(pp, task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if as_json:
        print_json(info)
        return

    print_info(f"Task: {info['name']}")
    print_info(f"Project: {info.get('project', '-')}")
    print_info(f"Status: {info.get('status', '-')}")
    print_info(f"Branch: {info.get('branch', '-')}")
    print_info(f"Created: {info.get('created_at', '-')}")
    print_info("")

    runs = info.get("runs", [])
    if runs:
        print_info("Run History:")
        for i, r in enumerate(runs, 1):
            status = r.get("status", "?")
            purpose = r.get("purpose", "?")
            agent = r.get("agent", "?")
            print_info(f"  #{i}  {purpose:<12} {agent:<8} {status}")
    else:
        print_info("No runs yet")

    # Show body
    body = info.get("body", "").strip()
    if body:
        print_info("")
        print_info(body)


@app.command()
def merge(
    task_name: str = typer.Argument(..., help="Task name"),
    project: str = typer.Option(None, "--project", help="Project path"),
) -> None:
    """Merge task branch into main and archive."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        commit = task.merge_task(pp, task_name)
        print_success(f"Task '{task_name}' merged ({commit[:7]})")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
