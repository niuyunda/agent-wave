"""agvv CLI entry point."""

from __future__ import annotations

import typer

from agvv.cli.checkpoint_cmd import app as checkpoint_app
from agvv.cli.daemon_cmd import app as daemon_app
from agvv.cli.project_cmd import app as project_app
from agvv.cli.run_cmd import app as run_app
from agvv.cli.session_cmd import app as session_app
from agvv.cli.task_cmd import app as task_app

app = typer.Typer(
    name="agvv",
    help="Deterministic project orchestration engine for AI coding agents.",
    no_args_is_help=True,
)

app.add_typer(daemon_app, name="daemon", help="Manage the agvv daemon.")
app.add_typer(project_app, name="project", help="Manage registered projects.")
app.add_typer(task_app, name="task", help="Manage tasks.")
app.add_typer(run_app, name="run", help="Manage runs.")
app.add_typer(session_app, name="session", help="Manage agent sessions.")
app.add_typer(checkpoint_app, name="checkpoint", help="View checkpoints.")


if __name__ == "__main__":
    app()
