"""checkpoint subcommand."""

from __future__ import annotations

import typer

from agvv.core import checkpoint, project as proj_mod
from agvv.utils.format import print_error, print_json

app = typer.Typer(no_args_is_help=True)


@app.command()
def show(
    task_name: str = typer.Argument(..., help="Task to inspect"),
    project: str = typer.Option(None, "--project", help="Target project path (optional if task name is unique)"),
) -> None:
    """Show latest checkpoint context, or latest-failure fallback info."""
    try:
        pp = proj_mod.resolve_project(project, task_name)
        info = checkpoint.show_checkpoint(pp, task_name)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    print_json(info)
