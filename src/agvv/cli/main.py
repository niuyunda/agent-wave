"""agvv CLI entry point."""

from __future__ import annotations

import typer

from agvv.cli.daemon_cmd import app as daemon_app
from agvv.cli.feedback_cmd import app as feedback_app
from agvv.cli.project_cmd import app as project_app
from agvv.cli.task_cmd import app as task_app

app = typer.Typer(
    name="agvv",
    help="Deterministic orchestration CLI for AI coding workflows in local Git repositories.",
    no_args_is_help=True,
)

app.add_typer(daemon_app, name="daemon", help="Control the background monitor daemon.")
app.add_typer(project_app, name="projects", help="View and manage registered project entries.")
app.add_typer(task_app, name="tasks", help="Create, inspect, and merge tasks.")
app.add_typer(feedback_app, name="feedback", help="File issues and sync agvv GitHub issues.")


if __name__ == "__main__":
    app()
