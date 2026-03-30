"""Session lifecycle management.

Wraps acpx session commands to provide session management for agvv tasks.
Each task maps to one acpx session (session name = task name, cwd = worktree).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agvv.core.acpx import acpx_invocation


def _run_with_order_fallback(
    *,
    worktree_path: Path,
    agent: str,
    args: list[str],
    timeout: int,
    capture_output: bool = True,
    text: bool = False,
) -> subprocess.CompletedProcess | None:
    """Run acpx command using preferred and legacy flag ordering.

    Newer acpx expects global flags (for example ``--cwd``/``--format``) before
    the agent token. Some environments still accept the legacy ordering where
    flags appear after the agent. Try preferred first, then fallback.
    """
    acpx_bin, acpx_args = acpx_invocation()
    preferred = [acpx_bin, *acpx_args, "--cwd", str(worktree_path), *args]
    legacy = [acpx_bin, *acpx_args, args[0], "--cwd", str(worktree_path), *args[1:]]

    for cmd in (preferred, legacy):
        try:
            return subprocess.run(
                cmd,
                check=True,
                capture_output=capture_output,
                text=text,
                timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return None


def ensure_session(project_path: Path, task_name: str, agent: str) -> bool:
    """Ensure a session exists for the task. Creates one if needed.

    Calls ``acpx --cwd <worktree> <agent> sessions ensure --name <task-name>``.
    Returns True on success. On failure, logs a warning but does not abort —
    the subsequent prompt may still work if the agent handles session creation
    implicitly.
    """
    worktree_path = project_path / "worktrees" / task_name
    result = _run_with_order_fallback(
        worktree_path=worktree_path,
        agent=agent,
        args=[
        agent,
        "sessions", "ensure",
        "--name", task_name,
        ],
        timeout=30,
    )
    return result is not None


def close_session(project_path: Path, task_name: str, agent: str) -> None:
    """Close the session for a task (soft-close, keeps history)."""
    worktree_path = project_path / "worktrees" / task_name
    _run_with_order_fallback(
        worktree_path=worktree_path,
        agent=agent,
        args=[agent, "sessions", "close", task_name],
        timeout=30,
    )


def get_session_status(project_path: Path, task_name: str, agent: str) -> dict | None:
    """Get session status. Returns parsed JSON or None if unavailable."""
    worktree_path = project_path / "worktrees" / task_name
    result = _run_with_order_fallback(
        worktree_path=worktree_path,
        agent=agent,
        args=[agent, "-s", task_name, "status"],
        timeout=10,
        text=True,
    )
    if result is None:
        return None
    payload = (result.stdout or "").strip()
    if not payload:
        return None

    # Prefer JSON output when available.
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass

    # Fallback: parse "key: value" lines from text status output.
    info: dict[str, str] = {}
    for line in payload.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip()] = value.strip()
    return info or None


def list_sessions(agent: str) -> list[dict]:
    """List all sessions for the given agent."""
    acpx_bin, acpx_args = acpx_invocation()
    cmd = [
        acpx_bin, *acpx_args,
        agent,
        "sessions", "list",
        "--format", "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        payload = (result.stdout or "").strip()
        if not payload:
            return []
        return json.loads(payload)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return []
