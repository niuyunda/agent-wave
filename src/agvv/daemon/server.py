"""Daemon process management and monitoring."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from agvv.core import config, run
from agvv.core.models import RunStatus, TaskStatus
from agvv.core.project import list_projects
from agvv.core.task import (
    list_tasks,
    mark_task_auto_managed,
    set_task_feedback,
    update_task_status,
)


def start_daemon() -> int:
    """Start the daemon process. Returns PID."""
    config.ensure_agvv_home()

    info = get_daemon_status()
    if info["running"]:
        raise RuntimeError(f"Daemon already running (PID {info['pid']})")

    env = os.environ.copy()
    env["AGVV_DAEMON_FOREGROUND"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")

    with open(config.DAEMON_LOG_FILE, "a", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "agvv.daemon.server"],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
            close_fds=True,
            env=env,
        )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        info = get_daemon_status()
        if info["running"] and info["pid"] == proc.pid:
            return proc.pid
        if proc.poll() is not None:
            detail = _read_daemon_log_tail()
            if detail:
                raise RuntimeError(f"Daemon failed to start: {detail}")
            raise RuntimeError("Daemon failed to start")
        time.sleep(0.05)

    try:
        os.kill(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    raise RuntimeError("Daemon failed to become ready")


def stop_daemon() -> None:
    """Stop the daemon process."""
    info = get_daemon_status()
    if not info["running"]:
        raise RuntimeError("Daemon not running")

    try:
        os.kill(info["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass

    config.DAEMON_PID_FILE.unlink(missing_ok=True)


def get_daemon_status() -> dict:
    """Check if daemon is running."""
    if not config.DAEMON_PID_FILE.exists():
        return {"running": False, "pid": None}

    try:
        pid = int(config.DAEMON_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return {"running": True, "pid": pid}
    except (ValueError, ProcessLookupError, PermissionError):
        config.DAEMON_PID_FILE.unlink(missing_ok=True)
        return {"running": False, "pid": None}


def _run_loop() -> None:
    """Main daemon loop."""
    signal.signal(signal.SIGTERM, _handle_sigterm)

    while True:
        try:
            _monitor_cycle()
        except SystemExit:
            break
        except Exception as e:
            _log(f"Monitor error: {e}")

        time.sleep(10)


def _serve_foreground() -> None:
    """Run daemon loop in current process."""
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    config.ensure_agvv_home()
    config.DAEMON_PID_FILE.write_text(str(os.getpid()))
    _log("Daemon started")
    try:
        _reconcile()
        _run_loop()
    except SystemExit:
        raise
    except Exception as exc:
        _log(f"Fatal daemon error: {exc}")
        traceback.print_exc()
        raise
    finally:
        config.DAEMON_PID_FILE.unlink(missing_ok=True)


def _monitor_cycle() -> None:
    """One monitoring cycle: auto-start and monitor active task runs."""
    for entry in list_projects():
        project_path = Path(entry.path)
        if not project_path.exists():
            continue

        for task_meta in list_tasks(project_path):
            task_name = task_meta.get("name")
            if not isinstance(task_name, str) or not task_name:
                continue

            if _is_auto_managed_pending_task(task_meta):
                _start_auto_managed_task(project_path, task_name, task_meta)
                continue

            if task_meta.get("status") != TaskStatus.running.value:
                continue

            latest = run.get_latest_run(project_path, task_name)
            if not latest:
                continue

            monitor_pid = latest.get("agent_pid") or latest.get("pid")
            if not monitor_pid:
                continue

            if not run.process_alive(monitor_pid):
                status = _determine_exit_status(project_path, task_name)
                if status == RunStatus.running:
                    continue
                final_status = (
                    run.finish_run(project_path, task_name, status) or status
                )
                _log(
                    f"Process {monitor_pid} for task {task_name} is dead, "
                    f"marking {final_status.value}"
                )
                continue

            started = latest.get("started_at", "")
            if started:
                try:
                    start_time = datetime.fromisoformat(started)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > config.DEFAULT_RUN_TIMEOUT:
                        run.finish_run(
                            project_path,
                            task_name,
                            RunStatus.timed_out,
                        )
                        _log(
                            f"Task {task_name} run timed out after {elapsed:.0f}s"
                        )
                except (ValueError, TypeError):
                    pass


def _is_auto_managed_pending_task(task_meta: dict) -> bool:
    if task_meta.get("status") != TaskStatus.pending.value:
        return False
    raw_auto_manage = task_meta.get("auto_manage")
    enabled = False
    if isinstance(raw_auto_manage, bool):
        enabled = raw_auto_manage
    elif isinstance(raw_auto_manage, str):
        enabled = raw_auto_manage.strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return False
    run_number = task_meta.get("run_number", 0)
    try:
        return int(run_number) == 0
    except (ValueError, TypeError):
        return False


def _auto_run_agent(project_path: Path, task_meta: dict | None = None) -> str:
    if task_meta:
        task_agent = task_meta.get("agent")
        if isinstance(task_agent, str) and task_agent.strip():
            return task_agent.strip()

    cfg_path = config.project_agvv_dir(project_path) / config.CONFIG_FILE
    if not cfg_path.exists():
        return "claude"
    try:
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return "claude"
    agent = payload.get("default_agent")
    if isinstance(agent, str) and agent.strip():
        return agent.strip()
    return "claude"


def _start_auto_managed_task(
    project_path: Path,
    task_name: str,
    task_meta: dict | None = None,
) -> None:
    agent = _auto_run_agent(project_path, task_meta)
    try:
        mark_task_auto_managed(project_path, task_name, enabled=True)
        set_task_feedback(
            project_path,
            task_name,
            "queued",
            f"Task queued for daemon run with agent '{agent}'.",
        )
        run.start_run(project_path, task_name, agent)
        _log(f"Auto-started task {task_name} in {project_path} with agent {agent}")
    except Exception as exc:
        update_task_status(project_path, task_name, TaskStatus.failed)
        set_task_feedback(
            project_path,
            task_name,
            "failed",
            f"Daemon failed to start task: {exc}",
        )
        _log(f"Auto-start failed for task {task_name} in {project_path}: {exc}")


def _reconcile() -> None:
    """Startup reconciliation: fix stale states."""
    _log("Running reconciliation...")
    for entry in list_projects():
        project_path = Path(entry.path)
        if not project_path.exists():
            continue

        for task_meta in list_tasks(project_path):
            if task_meta.get("status") != TaskStatus.running.value:
                continue

            task_name = task_meta["name"]
            latest = run.get_latest_run(project_path, task_name)
            if not latest:
                update_task_status(project_path, task_name, TaskStatus.failed)
                _log(f"Reconciled {task_name}: running -> failed (no active run)")
                continue

            monitor_pid = latest.get("agent_pid") or latest.get("pid")
            if monitor_pid and not run.process_alive(monitor_pid):
                status = _determine_exit_status(project_path, task_name)
                if status == RunStatus.running:
                    continue
                final_status = (
                    run.finish_run(project_path, task_name, status) or status
                )
                _log(
                    f"Reconciled {task_name}: running -> {final_status.value} "
                    f"(PID {monitor_pid} dead)"
                )


def _determine_exit_status(project_path: Path, task_name: str) -> RunStatus:
    """Infer terminal status from runtime sidecar file."""
    runtime_files = _runtime_files(project_path, task_name)
    if runtime_files:
        runtime_path = runtime_files[-1]
        for _ in range(40):
            payload = run.read_runtime_info(runtime_path)
            if not payload:
                return RunStatus.failed

            code = payload.get("exit_code")
            if code is not None:
                return run.status_from_exit_code(code)

            launcher_pid = payload.get("launcher_pid")
            if not (
                isinstance(launcher_pid, int)
                and run.process_alive(launcher_pid)
            ):
                return RunStatus.failed

            time.sleep(0.05)
        return RunStatus.running

    return RunStatus.failed


def _runtime_files(project_path: Path, task_name: str) -> list[Path]:
    run_dir = config.runs_dir(project_path, task_name)
    if run_dir.exists():
        return sorted(run_dir.glob("*.runtime.json"))
    return []


def _handle_sigterm(_signum: int, _frame: object) -> None:
    _log("Daemon stopping")
    config.DAEMON_PID_FILE.unlink(missing_ok=True)
    raise SystemExit(0)


def _log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] {msg}", flush=True)


def _read_daemon_log_tail(max_lines: int = 20) -> str | None:
    if not config.DAEMON_LOG_FILE.exists():
        return None
    try:
        lines = config.DAEMON_LOG_FILE.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return None
    tail = "\n".join(lines[-max_lines:]).strip()
    return tail or None


if __name__ == "__main__":
    if os.environ.get("AGVV_DAEMON_FOREGROUND") == "1":
        _serve_foreground()
