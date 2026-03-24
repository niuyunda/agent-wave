"""Tmux process lifecycle operations for orchestration."""

from __future__ import annotations

import subprocess
import shlex
from pathlib import Path
from typing import Callable

from agvv.orchestration.executor import CommandRunner, run_checked
from agvv.shared.errors import AgvvError

_run: CommandRunner = run_checked


def tmux_session_exists(session: str) -> bool:
    """Return whether a tmux session exists."""

    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AgvvError("tmux not found") from exc
    return result.returncode == 0


def tmux_kill_session(
    session: str,
    *,
    run_cmd: CommandRunner | None = None,
    session_exists: Callable[[str], bool] | None = None,
) -> None:
    """Kill tmux session if it exists."""

    runner = run_cmd or _run
    exists = session_exists or tmux_session_exists

    if not exists(session):
        return
    runner(["tmux", "kill-session", "-t", session])


def tmux_new_session(
    session: str,
    cwd: Path,
    command: str,
    *,
    run_cmd: CommandRunner | None = None,
    session_exists: Callable[[str], bool] | None = None,
) -> None:
    """Start a detached tmux session executing command in cwd."""

    runner = run_cmd or _run
    exists = session_exists or tmux_session_exists

    if exists(session):
        raise AgvvError(f"tmux session already exists: {session}")

    normalized_command = command.strip()
    if not normalized_command:
        raise AgvvError("tmux command cannot be empty.")

    runner(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session,
            "-c",
            str(cwd.expanduser().resolve()),
            f"exec {normalized_command}",
        ]
    )


def tmux_pipe_pane(
    session: str,
    output_log_path: Path,
    *,
    run_cmd: CommandRunner | None = None,
    session_exists: Callable[[str], bool] | None = None,
) -> None:
    """Pipe tmux pane output to file while preserving interactive TTY."""

    runner = run_cmd or _run
    exists = session_exists or tmux_session_exists

    if not exists(session):
        raise AgvvError(f"tmux session not found: {session}")

    resolved = output_log_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    # `cat >> file` appends all pane output and keeps the pane interactive.
    runner(
        [
            "tmux",
            "pipe-pane",
            "-o",
            "-t",
            session,
            f"cat >> {shlex.quote(str(resolved))}",
        ]
    )
