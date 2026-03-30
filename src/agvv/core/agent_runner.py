"""Small wrapper process that tracks the real agent child process.

The daemon should reason about the actual agent PID / process group rather than
the transient shell used to launch it. This runner writes a compact sidecar
JSON file with the runtime facts needed for monitoring and cleanup.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


child_process: subprocess.Popen[str] | None = None
child_pgid: int | None = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_runtime(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, sort_keys=True)
        tmp.write("\n")
        temp_path = Path(tmp.name)

    temp_path.replace(path)


def _forward_signal(signum: int, _frame: object) -> None:
    if child_process and child_process.poll() is None:
        try:
            if child_pgid:
                os.killpg(child_pgid, signum)
            else:
                child_process.send_signal(signum)
        except ProcessLookupError:
            pass


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _has_working_tree_changes(cwd: Path) -> bool:
    result = _run_git(cwd, ["status", "--porcelain"])
    return result.returncode == 0 and bool(result.stdout.strip())


def _has_staged_changes(cwd: Path) -> bool:
    result = _run_git(cwd, ["diff", "--cached", "--quiet"])
    return result.returncode == 1


def _auto_commit_if_needed(cwd: Path) -> None:
    purpose = os.environ.get("AGVV_RUN_PURPOSE")
    if purpose not in {"implement", "repair"}:
        return
    if not _has_working_tree_changes(cwd):
        return

    _run_git(cwd, ["add", "-A"])
    if not _has_staged_changes(cwd):
        return

    task_name = os.environ.get("AGVV_TASK_NAME", "").strip()
    message = f"agvv: checkpoint {task_name}" if task_name else "agvv: checkpoint"
    _run_git(cwd, ["commit", "-m", message])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: python -m agvv.core.agent_runner <runtime-json> <cmd>...", file=sys.stderr)
        return 64

    runtime_path = Path(args[0])
    command = args[1:]

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    launcher_pid = os.getpid()
    started_at = _now()
    _write_runtime(
        runtime_path,
        {
            "agent_pid": None,
            "exit_code": None,
            "finished_at": None,
            "launcher_pid": launcher_pid,
            "pgid": None,
            "started_at": started_at,
            "status": "starting",
        },
    )

    global child_process
    global child_pgid
    child_process = subprocess.Popen(command, start_new_session=True)
    child_pgid = os.getpgid(child_process.pid)

    _write_runtime(
        runtime_path,
        {
            "agent_pid": child_process.pid,
            "exit_code": None,
            "finished_at": None,
            "launcher_pid": launcher_pid,
            "pgid": child_pgid,
            "started_at": started_at,
            "status": "running",
        },
    )

    exit_code = child_process.wait()
    if exit_code == 0:
        _auto_commit_if_needed(Path.cwd())
    final_status = "completed" if exit_code == 0 else "failed"
    _write_runtime(
        runtime_path,
        {
            "agent_pid": child_process.pid,
            "exit_code": exit_code,
            "finished_at": _now(),
            "launcher_pid": launcher_pid,
            "pgid": child_pgid,
            "started_at": started_at,
            "status": final_status,
        },
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
