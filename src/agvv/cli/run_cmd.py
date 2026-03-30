"""run subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import run
from agvv.core.models import RunPurpose
from agvv.utils.format import print_error, print_info, print_json, print_success, print_table
from agvv.utils.git import GitError

app = typer.Typer(no_args_is_help=True)


@app.command()
def start(
    task_name: str = typer.Argument(..., help="Task to execute"),
    purpose: RunPurpose = typer.Option(..., "--purpose", help="Execution intent: implement, review, test, or repair"),
    agent: str = typer.Option("claude", "--agent", help="Agent type to invoke via acpx (for example: claude, codex)"),
    base_branch: str | None = typer.Option(
        None,
        "--base-branch",
        help="Existing branch or ref baseline (recommended for review/test)",
    ),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Start a task run and record runtime metadata."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        meta = run.start_run(pp, task_name, purpose, agent, base_branch=base_branch)
        print_success(f"Run started: {task_name} ({purpose.value}) agent={agent} PID={meta.pid}")
    except (ValueError, GitError) as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def stop(
    task_name: str = typer.Argument(..., help="Task with an active run"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Stop active run and ensure process group exits."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        run.stop_run(pp, task_name)
        print_success(f"Run stopped: {task_name}")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def status_cmd(
    project: str = typer.Option(None, "--project", help="Filter to one project path (omit for all registered projects)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List currently active runs."""
    if project:
        projects = [Path(project).resolve()]
    else:
        projects = [Path(e.path) for e in proj_mod.list_projects()]

    if not projects:
        print_error("No projects registered")
        raise typer.Exit(1)

    all_runs = []
    for pp in projects:
        for r in run.list_runs(pp):
            r["project"] = str(pp)
            all_runs.append(r)

    if as_json:
        # Clean up non-serializable fields
        for r in all_runs:
            r.pop("_file", None)
            r.pop("_task_status", None)
        print_json(all_runs)
        return

    if not all_runs:
        print_info("No active runs")
        return

    columns = ["TASK", "PURPOSE", "AGENT", "STATUS", "PID"]
    rows = []
    for r in all_runs:
        rows.append([
            r.get("task", "?"),
            r.get("purpose", "-"),
            r.get("agent", "-"),
            r.get("status", "-"),
            str(r.get("pid", "-")),
        ])
    print_table(columns, rows)
