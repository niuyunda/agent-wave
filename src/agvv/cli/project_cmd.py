"""project subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project, task
from agvv.utils.format import print_error, print_json, print_success, print_table

app = typer.Typer(no_args_is_help=True)


def _project_counts(pp: Path) -> dict:
    tasks = task.list_tasks(pp) if pp.exists() else []
    archived = task.count_archived_tasks(pp) if pp.exists() else 0
    return {
        "tasks": len(tasks) + archived,
        "running": sum(1 for t in tasks if t.get("status") == "running"),
        "pending": sum(1 for t in tasks if t.get("status") == "pending"),
        "done": archived,
        "failed": sum(1 for t in tasks if t.get("status") in {"failed", "blocked"}),
    }


@app.command()
def add(
    path: str = typer.Argument(..., help="Repository directory to register"),
) -> None:
    """Register a repository and initialize `.agvv/` metadata."""
    try:
        entry = project.add_project(Path(path))
        print_success(f"Project registered: {entry.path}")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List registered repositories with task/run summary counts."""
    entries = project.list_projects()
    if not entries:
        print_error("No projects registered")
        raise typer.Exit(1)

    if as_json:
        data = []
        for e in entries:
            counts = _project_counts(Path(e.path))
            data.append({"path": e.path, **counts})
        print_json(data)
        return

    columns = ["PROJECT", "TASKS", "RUNNING", "PENDING", "DONE", "FAILED"]
    rows = []
    for e in entries:
        c = _project_counts(Path(e.path))
        rows.append([
            e.path,
            str(c["tasks"]),
            str(c["running"]),
            str(c["pending"]),
            str(c["done"]),
            str(c["failed"]),
        ])
    print_table(columns, rows)


@app.command()
def remove(
    path: str = typer.Argument(..., help="Registered repository directory to remove"),
) -> None:
    """Remove project from registry only (keeps repository files)."""
    try:
        project.remove_project(Path(path))
        print_success(f"Project removed: {path}")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
