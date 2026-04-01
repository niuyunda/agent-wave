"""session subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import session
from agvv.utils.format import print_error, print_json, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def ensure(
    task_name: str = typer.Argument(..., help="Task whose session should exist"),
    agent: str = typer.Option(..., "--agent", help="Agent type (for example: codex)"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Create or reuse a persistent session for a task."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        created_or_found = session.ensure_session(pp, task_name, agent)
        print_success(
            "Session ensured",
            project=str(pp),
            task=task_name,
            agent=agent,
            ensured=created_or_found,
        )
    except (ValueError, Exception) as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def close(
    task_name: str = typer.Argument(..., help="Task whose session should be closed"),
    agent: str = typer.Option(..., "--agent", help="Agent type"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Soft-close a task session while keeping history."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        session.close_session(pp, task_name, agent)
        print_success("Session closed", project=str(pp), task=task_name, agent=agent)
    except (ValueError, Exception) as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def status_cmd(
    task_name: str = typer.Argument(..., help="Task to inspect session for"),
    agent: str = typer.Option(..., "--agent", help="Agent type"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Show runtime status of a task session."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    info = session.get_session_status(pp, task_name, agent)
    if not info:
        print_json({"task": task_name, "agent": agent, "project": str(pp), "active": False})
        return

    payload = dict(info)
    payload.update({"task": task_name, "agent": agent, "project": str(pp), "active": True})
    print_json(payload)


@app.command("list")
def list_cmd(
    agent: str = typer.Option(..., "--agent", help="Agent type"),
) -> None:
    """List all known sessions for an agent type."""
    sessions = session.list_sessions(agent)
    print_json(sessions)
