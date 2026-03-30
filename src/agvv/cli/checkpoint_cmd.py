"""checkpoint subcommand."""

from __future__ import annotations

import typer

from agvv.core import checkpoint, project as proj_mod
from agvv.utils.format import print_error, print_info, print_json

app = typer.Typer(no_args_is_help=True)


@app.command()
def show(
    task_name: str = typer.Argument(..., help="Task to inspect"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Show latest checkpoint context, or latest-failure fallback info."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        info = checkpoint.show_checkpoint(pp, task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if as_json:
        print_json(info)
        return

    if not info.get("checkpoint"):
        print_info(info.get("message", "No checkpoint found"))
        return

    print_info(f"Task: {info['task']}")
    print_info(f"Checkpoint: {info['checkpoint']}")
    print_info(f"Purpose: {info.get('purpose', '-')}")
    print_info(f"Agent: {info.get('agent', '-')}")
    print_info(f"Finished: {info.get('finished_at', '-')}")

    summary = info.get("summary", "").strip()
    if summary:
        print_info("")
        print_info(summary)
