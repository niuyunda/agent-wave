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
            child_process.send_signal(signum)
        except ProcessLookupError:
            pass


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
    pgid = os.getpgrp()
    started_at = _now()
    _write_runtime(
        runtime_path,
        {
            "agent_pid": None,
            "exit_code": None,
            "finished_at": None,
            "launcher_pid": launcher_pid,
            "pgid": pgid,
            "started_at": started_at,
            "status": "starting",
        },
    )

    global child_process
    child_process = subprocess.Popen(command)

    _write_runtime(
        runtime_path,
        {
            "agent_pid": child_process.pid,
            "exit_code": None,
            "finished_at": None,
            "launcher_pid": launcher_pid,
            "pgid": pgid,
            "started_at": started_at,
            "status": "running",
        },
    )

    exit_code = child_process.wait()
    _write_runtime(
        runtime_path,
        {
            "agent_pid": child_process.pid,
            "exit_code": exit_code,
            "finished_at": _now(),
            "launcher_pid": launcher_pid,
            "pgid": pgid,
            "started_at": started_at,
            "status": "finished",
        },
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
