"""daemon subcommand."""

from __future__ import annotations

import json

import typer

from agvv.core import config
from agvv.daemon.server import get_daemon_status, start_daemon, stop_daemon
from agvv.utils.format import print_error, print_info, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def start(
    sync_interval: int | None = typer.Option(
        None,
        "--sync-interval",
        help="Minutes between GitHub issues sync (0 to disable, omit to keep current)",
    ),
) -> None:
    """Start background monitor for active runs."""
    # Persist sync_interval to daemon config
    cfg = {}
    cfg_path = config.daemon_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except (ValueError, OSError):
            cfg = {}
    if sync_interval is not None:
        cfg["sync_interval"] = sync_interval
        cfg_path.write_text(json.dumps(cfg))
    try:
        pid = start_daemon()
        print_success(f"Daemon started (PID {pid})")
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
    if info["running"]:
        print_info(f"Daemon running (PID {info['pid']})")
    else:
        print_info("Daemon not running")
