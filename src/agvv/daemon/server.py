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

from agvv.core import config
from agvv.core.models import RunPurpose, RunStatus, TaskStatus
from agvv.core.project import list_projects
from agvv.core.run import finish_run, get_latest_run, start_run
from agvv.core.task import (
    list_tasks,
    mark_task_auto_managed,
    set_task_feedback,
    update_task_status,
)


def start_daemon() -> int:
    """Start the daemon process. Returns PID."""
    config.ensure_agvv_home()

    # Check if already running
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
        os.kill(pid, 0)  # Check if process exists
        return {"running": True, "pid": pid}
    except (ValueError, ProcessLookupError, PermissionError):
        config.DAEMON_PID_FILE.unlink(missing_ok=True)
        return {"running": False, "pid": None}


def _load_daemon_config() -> dict:
    """Load daemon config from ``~/.agvv/daemon.conf``."""
    cfg_path = config.daemon_config_path()
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text())
    except (ValueError, OSError):
        return {}


def _issues_sync(repo: str) -> int:
    """Fetch open GitHub issues and cache to ``~/.agvv/issues.json``. Returns count of issues."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--repo", repo,
                "--state", "open",
                "--json", "number,title,url,createdAt,labels",
                "--limit", "100",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            _log(f"issues sync: gh failed: {result.stderr.strip()}")
            return 0
        issues = json.loads(result.stdout)
        config.issues_cache_path().write_text(json.dumps(issues, indent=2))
        count = len(issues)
        _log(f"issues sync: cached {count} open issues from {repo}")
        return count
    except subprocess.TimeoutExpired:
        _log("issues sync: gh timed out")
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        _log(f"issues sync error: {e}")
    return 0


def _run_loop() -> None:
    """Main daemon loop: monitor runs, detect timeouts/stalls, and periodically sync issues."""
    signal.signal(signal.SIGTERM, _handle_sigterm)

    daemon_cfg = _load_daemon_config()
    sync_interval: int | None = daemon_cfg.get("sync_interval")
    last_sync_at = time.monotonic()
    agvv_repo = config.DEFAULT_AGVV_REPO

    if sync_interval:
        _log(f"Issues sync enabled (every {sync_interval} min)")
        _issues_sync(agvv_repo)
        last_sync_at = time.monotonic()

    while True:
        try:
            _monitor_cycle()
        except SystemExit:
            break
        except Exception as e:
            _log(f"Monitor error: {e}")

        # Check if it's time to sync issues
        if sync_interval:
            elapsed = (time.monotonic() - last_sync_at) / 60.0
            if elapsed >= sync_interval:
                _issues_sync(agvv_repo)
                last_sync_at = time.monotonic()

        time.sleep(10)


def _serve_foreground() -> None:
    """Run the daemon loop in the current process."""
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
    """One monitoring cycle: check all active runs."""
    for entry in list_projects():
        project_path = Path(entry.path)
        if not project_path.exists():
            continue

        tasks = list_tasks(project_path)
        for t in tasks:
            task_name = t.get("name")
            if not isinstance(task_name, str) or not task_name:
                continue

            if _is_auto_managed_pending_task(t):
                _start_auto_managed_task(project_path, task_name, t)
                continue

            if t.get("status") != TaskStatus.running.value:
                continue

            latest = get_latest_run(project_path, task_name)
            if not latest:
                continue

            monitor_pid = latest.get("agent_pid") or latest.get("pid")
            if not monitor_pid:
                continue

            # Check if process is still alive
            if not _process_alive(monitor_pid):
                status = _determine_exit_status(project_path, task_name)
                if status == RunStatus.running:
                    continue
                final_status = finish_run(project_path, task_name, status) or status
                _log(f"Process {monitor_pid} for task {task_name} is dead, marking {final_status.value}")
                continue

            # Check timeout
            started = latest.get("started_at", "")
            if started:
                try:
                    start_time = datetime.fromisoformat(started)
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > config.DEFAULT_RUN_TIMEOUT:
                        _kill_process_group(latest)
                        final_status = finish_run(project_path, task_name, RunStatus.timed_out) or RunStatus.timed_out
                        _log(f"Task {task_name} run timed out after {elapsed:.0f}s; marking {final_status.value}")
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


def _start_auto_managed_task(project_path: Path, task_name: str, task_meta: dict | None = None) -> None:
    agent = _auto_run_agent(project_path, task_meta)
    try:
        mark_task_auto_managed(project_path, task_name, enabled=True)
        set_task_feedback(
            project_path,
            task_name,
            "queued",
            f"Task queued for daemon execution with agent '{agent}'.",
        )
        start_run(project_path, task_name, RunPurpose.implement, agent)
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

        tasks = list_tasks(project_path)
        for t in tasks:
            if t.get("status") != TaskStatus.running.value:
                continue

            task_name = t["name"]
            latest = get_latest_run(project_path, task_name)
            if not latest:
                # Status says running but no active run record
                update_task_status(project_path, task_name, TaskStatus.failed)
                _log(f"Reconciled {task_name}: running → failed (no active run)")
                continue

            monitor_pid = latest.get("agent_pid") or latest.get("pid")
            if monitor_pid and not _process_alive(monitor_pid):
                status = _determine_exit_status(project_path, task_name)
                if status == RunStatus.running:
                    continue
                final_status = finish_run(project_path, task_name, status) or status
                _log(f"Reconciled {task_name}: running → {final_status.value} (PID {monitor_pid} dead)")


def _determine_exit_status(project_path: Path, task_name: str) -> RunStatus:
    """Check for an exit code sidecar file to distinguish success from failure."""
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return RunStatus.failed

    runtime_files = sorted(rd.glob("*.runtime.json"))
    if runtime_files:
        runtime_path = runtime_files[-1]
        for _ in range(40):
            try:
                payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            except (ValueError, OSError, json.JSONDecodeError):
                return RunStatus.failed

            code = payload.get("exit_code")
            if code is not None:
                return RunStatus.completed if int(code) == 0 else RunStatus.failed

            launcher_pid = payload.get("launcher_pid")
            if not (isinstance(launcher_pid, int) and _process_alive(launcher_pid)):
                return RunStatus.failed

            # Agent is already gone, but launcher may still be finalizing runtime metadata.
            time.sleep(0.05)
        return RunStatus.running

    exitcode_files = sorted(rd.glob("*.exitcode"))
    if exitcode_files:
        try:
            code = int(exitcode_files[-1].read_text().strip())
            exitcode_files[-1].unlink()
            return RunStatus.completed if code == 0 else RunStatus.failed
        except (ValueError, OSError):
            return RunStatus.failed

    return RunStatus.failed


def _process_alive(pid: int) -> bool:
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            stat_fields = proc_stat.read_text(encoding="utf-8").split()
            if len(stat_fields) >= 3 and stat_fields[2] == "Z":
                return False
        except OSError:
            pass
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _kill_process(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def _kill_process_group(active: dict) -> None:
    pgid = active.get("pgid")
    pid = active.get("agent_pid") or active.get("pid")
    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        elif pid:
            _kill_process(pid)
    except (ProcessLookupError, PermissionError):
        pass


def _handle_sigterm(signum: int, frame: object) -> None:
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
        lines = config.DAEMON_LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    tail = "\n".join(lines[-max_lines:]).strip()
    return tail or None


if __name__ == "__main__":
    if os.environ.get("AGVV_DAEMON_FOREGROUND") == "1":
        _serve_foreground()
