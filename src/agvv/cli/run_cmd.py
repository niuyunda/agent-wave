"""run subcommand."""

from __future__ import annotations

from pathlib import Path

import typer

from agvv.core import project as proj_mod
from agvv.core import run
from agvv.core.models import RunPurpose
from agvv.utils.format import print_error, print_json, print_success
from agvv.utils.git import GitError

app = typer.Typer(no_args_is_help=True)


def _serialize_run_payload(entry: dict) -> dict:
    payload = dict(entry)
    payload.pop("_file", None)
    payload.pop("_task_status", None)
    return payload


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
        print_success(
            "Run started",
            project=str(pp),
            task=task_name,
            run=meta.model_dump(mode="json"),
        )
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
        print_success("Run stopped", project=str(pp), task=task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def status_cmd(
    project: str = typer.Option(None, "--project", help="Filter to one project path (omit for all registered projects)"),
) -> None:
    """List currently active runs."""
    if project:
        projects = [Path(project).resolve()]
    else:
        projects = [Path(e.path) for e in proj_mod.list_projects()]

    all_runs = []
    for pp in projects:
        for r in run.list_runs(pp):
            r["project"] = str(pp)
            all_runs.append(_serialize_run_payload(r))

    print_json(all_runs)
