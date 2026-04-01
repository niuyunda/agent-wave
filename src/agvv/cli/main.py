"""agvv CLI entry point."""

from __future__ import annotations

import typer

from agvv.cli.checkpoint_cmd import app as checkpoint_app
from agvv.cli.daemon_cmd import app as daemon_app
from agvv.cli.feedback_cmd import app as feedback_app
from agvv.cli.project_cmd import app as project_app
from agvv.cli.run_cmd import app as run_app
from agvv.cli.session_cmd import app as session_app
from agvv.cli.task_cmd import app as task_app

app = typer.Typer(
    name="agvv",
    help="Deterministic orchestration CLI for AI coding workflows in local Git repositories.",
    no_args_is_help=True,
)

app.add_typer(daemon_app, name="daemon", help="Control the background monitor daemon.")
app.add_typer(project_app, name="project", help="Register repositories and view project-level summaries.")
app.add_typer(task_app, name="task", help="Create, inspect, and merge tasks.")
app.add_typer(run_app, name="run", help="Start, stop, and inspect task runs.")
app.add_typer(session_app, name="session", help="Manage persistent acpx sessions per task.")
app.add_typer(checkpoint_app, name="checkpoint", help="Inspect latest durable checkpoint context.")
app.add_typer(feedback_app, name="feedback", help="File issues and sync agvv GitHub issues.")


if __name__ == "__main__":
    app()
