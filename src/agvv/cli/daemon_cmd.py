"""daemon subcommand."""

from __future__ import annotations

import typer

from agvv.daemon.server import get_daemon_status, start_daemon, stop_daemon
from agvv.utils.format import print_error, print_info, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def start() -> None:
    """Start the agvv daemon."""
    try:
        pid = start_daemon()
        print_success(f"Daemon started (PID {pid})")
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the agvv daemon."""
    try:
        stop_daemon()
        print_success("Daemon stopped")
    except Exception as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show daemon status."""
    info = get_daemon_status()
    if info["running"]:
        print_info(f"Daemon running (PID {info['pid']})")
    else:
        print_info("Daemon not running")
