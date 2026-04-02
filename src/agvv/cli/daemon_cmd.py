"""daemon subcommand."""

from __future__ import annotations

import typer

from agvv.core import config
from agvv.daemon.server import get_daemon_status, start_daemon, stop_daemon
from agvv.utils.format import print_error, print_json, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def start() -> None:
    """Start background monitor for active task runs."""
    config.ensure_agvv_home()
    try:
        pid = start_daemon()
        print_success("Daemon started", pid=pid)
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop background monitor daemon."""
    try:
        stop_daemon()
        print_success("Daemon stopped")
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show whether daemon is running and its PID."""
    info = get_daemon_status()
    print_json(info)
