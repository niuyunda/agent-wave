"""project subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project, task
from agvv.utils.format import print_error, print_json, print_success

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


def _project_counts(pp: Path) -> dict:
    tasks = task.list_tasks(pp) if pp.exists() else []
    archived = task.count_archived_tasks(pp) if pp.exists() else 0
    done_active = sum(1 for t in tasks if t.get("status") == "done")
    return {
        "tasks": len(tasks) + archived,
        "running": sum(1 for t in tasks if t.get("status") == "running"),
        "pending": sum(1 for t in tasks if t.get("status") == "pending"),
        "done": archived + done_active,
        "failed": sum(1 for t in tasks if t.get("status") in {"failed", "blocked"}),
    }


def _list_projects() -> None:
    """List registered repositories with task/run summary counts."""
    entries = project.list_projects()
    data = []
    for e in entries:
        c = _project_counts(Path(e.path))
        data.append({"path": e.path, **c})
    print_json(data)


def _project_status_payload(pp: Path) -> dict:
    summary = {"path": str(pp), **_project_counts(pp)}
    if not pp.exists():
        summary["exists"] = False
        summary["task_statuses"] = []
        return summary

    summary["exists"] = True
    summary["task_statuses"] = [
        {
            "name": item.get("name"),
            "status": item.get("status"),
            "feedback_status": item.get("feedback_status"),
            "last_agent": item.get("last_agent"),
            "last_status": item.get("last_status"),
            "run_number": item.get("run_number"),
        }
        for item in task.list_tasks(pp)
    ]
    return summary


@app.callback()
def projects(ctx: typer.Context) -> None:
    """View and manage registered project entries."""
    if ctx.invoked_subcommand is None:
        _list_projects()


@app.command("list")
def list_cmd() -> None:
    """Alias for `agvv projects`."""
    _list_projects()


@app.command("show")
def show(
    path: str = typer.Argument(..., help="Project directory path"),
) -> None:
    """Show one project's detailed status."""
    print_json(_project_status_payload(Path(path).resolve()))


@app.command()
def remove(
    path: str = typer.Argument(..., help="Registered repository directory to remove"),
) -> None:
    """Remove project from registry only (keeps repository files)."""
    try:
        project.remove_project(Path(path))
        print_success("Project removed", path=str(Path(path).resolve()))
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
