"""ACP session lifecycle operations for orchestration (replaces tmux_ops)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Literal

from agvv.orchestration.executor import run_checked
from agvv.shared.errors import AgvvError

DEFAULT_ACPX_CMD = "acpx"


class AcpSessionStatus:
    """Parsed acpx status output."""

    def __init__(
        self,
        state: Literal["running", "dead", "no_session"] | None,
        pid: int | None,
        session_id: str | None,
        uptime: str | None,
        last_prompt: str | None,
        last_exit: str | None,
    ):
        self.state = state
        self.pid = pid
        self.session_id = session_id
        self.uptime = uptime
        self.last_prompt = last_prompt
        self.last_exit = last_exit


def _parse_status_text(stdout: str) -> AcpSessionStatus:
    """Parse text-format status output."""
    state = None
    pid = None
    session_id = None
    uptime = None
    last_prompt = None
    last_exit = None

    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        if key == "state":
            state = value
        elif key == "pid":
            pid = int(value) if value and value != "null" else None
        elif key in ("session_id", "sessionid"):
            session_id = value if value and value != "null" else None
        elif key == "uptime":
            uptime = value if value and value != "null" else None
        elif key in ("last_prompt", "lastprompt"):
            last_prompt = value if value and value != "null" else None
        elif key in ("last_exit", "lastexit"):
            last_exit = value if value and value != "null" else None

    if state is None:
        state = "no_session"
    elif state not in ("running", "dead"):
        state = "no_session"

    return AcpSessionStatus(state, pid, session_id, uptime, last_prompt, last_exit)


def acpx_session_status(
    agent: str,
    session: str,
    cwd: Path,
    *,
    run_cmd: Callable | None = None,
) -> AcpSessionStatus:
    """Get acpx session status for a named session in cwd."""
    runner = run_cmd or run_checked

    # Try JSON first
    try:
        result = runner(
            [DEFAULT_ACPX_CMD, agent, "status", "-s", session, "--format", "json"],
            cwd=cwd,
            timeout_seconds=10,
        )
        data = json.loads(result.stdout.strip())
        return AcpSessionStatus(
            state=data.get("state"),
            pid=data.get("pid"),
            session_id=data.get("sessionId"),
            uptime=data.get("uptime"),
            last_prompt=data.get("lastPromptAt"),
            last_exit=data.get("lastExit"),
        )
    except Exception:
        pass

    # Fallback: text format
    try:
        result = runner(
            [DEFAULT_ACPX_CMD, agent, "status", "-s", session],
            cwd=cwd,
            timeout_seconds=10,
        )
        return _parse_status_text(result.stdout)
    except Exception:
        return AcpSessionStatus(None, None, None, None, None, None)


def acpx_session_exists(
    agent: str,
    session: str,
    cwd: Path,
    *,
    run_cmd: Callable | None = None,
) -> bool:
    """Return whether an acpx session exists (running or dead but not closed)."""
    status = acpx_session_status(agent, session, cwd, run_cmd=run_cmd)
    return status.state in ("running", "dead")


def acpx_session_running(
    agent: str,
    session: str,
    cwd: Path,
    *,
    run_cmd: Callable | None = None,
) -> bool:
    """Return whether the acpx session process is currently alive."""
    status = acpx_session_status(agent, session, cwd, run_cmd=run_cmd)
    return status.state == "running"


def acpx_create_session(
    agent: str,
    session: str,
    cwd: Path,
    *,
    run_cmd: Callable | None = None,
) -> None:
    """Create a new named acpx session in cwd."""
    runner = run_cmd or run_checked
    runner(
        [DEFAULT_ACPX_CMD, agent, "sessions", "new", "--name", session],
        cwd=cwd,
        timeout_seconds=30,
    )


def acpx_close_session(
    agent: str,
    session: str,
    cwd: Path,
    *,
    run_cmd: Callable | None = None,
) -> None:
    """Soft-close an acpx session."""
    runner = run_cmd or run_checked
    try:
        runner(
            [DEFAULT_ACPX_CMD, agent, "sessions", "close", session],
            cwd=cwd,
            timeout_seconds=15,
        )
    except AgvvError:
        pass  # ignore if already closed


def acpx_send_prompt(
    agent: str,
    session: str,
    cwd: Path,
    prompt_path: Path,
    output_log_path: Path | None = None,
    *,
    permission_mode: str = "--approve-all",
    timeout_seconds: int | None = None,
    run_cmd: Callable | None = None,
) -> None:
    """Send prompt via acpx and wait for completion."""
    runner = run_cmd or run_checked

    args = [
        DEFAULT_ACPX_CMD,
        permission_mode,
        agent,
        "-s",
        session,
        "--file",
        str(prompt_path),
    ]

    try:
        result = runner(args, cwd=cwd, timeout_seconds=timeout_seconds)
        if output_log_path and result.stdout:
            output_log_path.parent.mkdir(parents=True, exist_ok=True)
            output_log_path.write_text(result.stdout, encoding="utf-8")
    except subprocess.TimeoutExpired:
        raise AgvvError(f"Prompt timed out after {timeout_seconds}s")
