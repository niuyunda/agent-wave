"""Task run lifecycle management."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import frontmatter

from agvv.core import config
from agvv.core.acpx import acpx_invocation, acpx_opts, check_acpx_auth
from agvv.core.models import RunMeta, RunStatus, TaskStatus
from agvv.core.task import (
    is_task_auto_managed,
    next_run_number,
    set_task_feedback,
    update_task_status,
)
from agvv.utils import git, markdown

_TERMINAL_RUNTIME_STATUSES = {"finished", "failed", "completed", "stopped"}


def read_runtime_info(runtime_file: Path) -> dict:
    """Read runtime sidecar JSON. Returns an empty dict on failure."""
    if not runtime_file.exists():
        return {}
    try:
        return json.loads(runtime_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def process_alive(pid: int | None) -> bool:
    """Return True when PID exists and is not a zombie."""
    if not pid:
        return False
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


def status_from_exit_code(
    exit_code: object,
    *,
    none_status: RunStatus = RunStatus.failed,
) -> RunStatus:
    """Map an exit code value to a run status."""
    if exit_code is None:
        return none_status
    try:
        return RunStatus.completed if int(exit_code) == 0 else RunStatus.failed
    except (ValueError, TypeError):
        return RunStatus.failed


def status_from_runtime(runtime_or_latest: dict) -> RunStatus:
    """Infer terminal run status from runtime-side fields."""
    runtime_status = runtime_or_latest.get("status")
    if runtime_status == RunStatus.stopped.value:
        return RunStatus.stopped
    return status_from_exit_code(runtime_or_latest.get("exit_code"))


def start_run(project_path: Path, task_name: str, agent: str) -> RunMeta:
    """Start a new task run."""
    auth_warning = check_acpx_auth()
    if auth_warning:
        import warnings

        warnings.warn(auth_warning)

    task_file = config.task_file(project_path, task_name)
    if not task_file.exists():
        raise ValueError(f"Task '{task_name}' not found")

    active = get_active_run(project_path, task_name)
    if active:
        raise ValueError(
            f"Task '{task_name}' already has an active run (PID {active.get('pid')})"
        )

    branch = f"{config.BRANCH_PREFIX}{task_name}"
    run_num = next_run_number(project_path, task_name)
    worktree_path = project_path / "worktrees" / task_name

    worktree_created = False
    if not worktree_path.exists():
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        branch_start = None
        if not git.ref_exists(project_path, branch):
            branch_start = git.get_main_branch(project_path)
        git.create_worktree(
            project_path,
            worktree_path,
            branch,
            start_ref=branch_start,
        )
        worktree_created = True
        _run_hook(project_path, "after_create", worktree_path)
    else:
        try:
            _checkout_task_branch(project_path, worktree_path, branch)
        except git.GitError as e:
            raise ValueError(
                f"Failed to switch worktree '{task_name}' to branch '{branch}': {e}"
            ) from e

    try:
        _run_hook(project_path, "before_run", worktree_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if worktree_created:
            try:
                git.remove_worktree(project_path, worktree_path)
            except git.GitError:
                pass
        raise ValueError(f"before_run hook failed: {e}") from e

    task_post = frontmatter.load(str(task_file))
    prompt = _build_run_prompt(task_post.content)

    base_commit = None
    try:
        base_commit = git.get_latest_commit(worktree_path)
    except git.GitError:
        pass

    agent_cmd = _build_acpx_prompt_command(agent, prompt)
    runtime_file = _runtime_file(project_path, task_name, run_num)
    log_file = _run_log_file(project_path, task_name, run_num)
    runtime_env = os.environ.copy()
    runtime_env["AGVV_RUN_PURPOSE"] = "implement"
    runtime_env["AGVV_TASK_NAME"] = task_name
    runtime_env["AGVV_EXEC_AGENT"] = agent
    with log_file.open("ab") as log_handle:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agvv.core.agent_runner",
                str(runtime_file),
                *agent_cmd,
            ],
            cwd=worktree_path,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
            env=runtime_env,
        )

    runtime = _wait_for_runtime_file(runtime_file)

    meta = RunMeta(
        agent=agent,
        pid=runtime.get("agent_pid") or proc.pid,
        launcher_pid=proc.pid,
        pgid=runtime.get("pgid"),
        base_branch=branch,
        base_commit=base_commit,
    )
    run_file = config.runs_dir(project_path, task_name) / f"{run_num:03d}.md"
    markdown.write_md(run_file, meta.model_dump(mode="json"), "")

    update_task_status(project_path, task_name, TaskStatus.running)
    set_task_feedback(
        project_path,
        task_name,
        "running",
        f"Run started with agent '{agent}'.",
    )
    return meta


def stop_run(project_path: Path, task_name: str) -> None:
    """Stop active run for a task."""
    active = get_active_run(project_path, task_name)
    if not active:
        raise ValueError(f"No active run for task '{task_name}'")
    if not _terminate_active_run(active):
        raise ValueError(f"Failed to stop task '{task_name}': process is still alive")
    _finish_run(project_path, task_name, RunStatus.stopped)


def get_active_run(project_path: Path, task_name: str) -> dict | None:
    """Get the currently active run for a task, or None."""
    latest = get_latest_run(project_path, task_name)
    if not latest:
        return None
    if latest.get("_task_status") != RunStatus.running.value:
        return None

    if latest.get("agent_pid"):
        latest["pid"] = latest["agent_pid"]

    runtime_status = latest.get("status")
    if runtime_status in _TERMINAL_RUNTIME_STATUSES or latest.get("exit_code") is not None:
        _finish_run(project_path, task_name, status_from_runtime(latest))
        return None

    monitor_pid = latest.get("agent_pid") or latest.get("pid")
    if monitor_pid and not process_alive(monitor_pid):
        launcher_pid = latest.get("launcher_pid")
        if latest.get("exit_code") is None and isinstance(launcher_pid, int) and process_alive(launcher_pid):
            runtime_file = _runtime_file_for_run_file(latest["_file"])
            for _ in range(40):
                refreshed = read_runtime_info(runtime_file)
                if refreshed:
                    latest.update(refreshed)
                runtime_status = latest.get("status")
                if runtime_status in _TERMINAL_RUNTIME_STATUSES or latest.get("exit_code") is not None:
                    _finish_run(project_path, task_name, status_from_runtime(latest))
                    return None
                if not process_alive(launcher_pid):
                    break
                time.sleep(0.05)
            if isinstance(launcher_pid, int) and process_alive(launcher_pid):
                return latest
        _finish_run(project_path, task_name, status_from_runtime(latest))
        return None
    return latest


def get_latest_run(project_path: Path, task_name: str) -> dict | None:
    """Get latest run record with runtime details if available."""
    run_files = _run_files(project_path, task_name)
    if not run_files:
        return None

    latest_file = run_files[-1]
    latest = markdown.read_frontmatter(latest_file)
    latest["_task_status"] = latest.get("status")
    if latest["_task_status"] == RunStatus.running.value:
        latest.update(read_runtime_info(_runtime_file_for_run_file(latest_file)))
    latest["_file"] = latest_file
    return latest


def finish_run(
    project_path: Path,
    task_name: str,
    status: RunStatus,
) -> RunStatus | None:
    """Mark active run as finished with given status."""
    return _finish_run(project_path, task_name, status)


def _finish_run(
    project_path: Path,
    task_name: str,
    status: RunStatus,
) -> RunStatus | None:
    """Internal: update latest run record to terminal state."""
    run_files = _run_files(project_path, task_name)
    if not run_files:
        return None

    latest_file = run_files[-1]
    post = frontmatter.load(str(latest_file))
    runtime = read_runtime_info(_runtime_file_for_run_file(latest_file))

    effective_status = status
    finish_reason = None
    error_message = None

    exit_code = runtime.get("exit_code")
    if exit_code is not None:
        post.metadata["exit_code"] = exit_code

    post.metadata["status"] = status.value
    post.metadata["finished_at"] = runtime.get("finished_at") or datetime.now().isoformat(
        timespec="seconds"
    )
    if runtime.get("launcher_pid") and not post.metadata.get("launcher_pid"):
        post.metadata["launcher_pid"] = runtime["launcher_pid"]
    if runtime.get("pgid") and not post.metadata.get("pgid"):
        post.metadata["pgid"] = runtime["pgid"]
    if runtime.get("agent_pid"):
        post.metadata["pid"] = runtime["agent_pid"]

    base_commit = post.metadata.get("base_commit")

    if status == RunStatus.completed:
        worktree_path = project_path / "worktrees" / task_name
        if worktree_path.exists():
            try:
                latest_commit = git.get_latest_commit(worktree_path)
                checkpoint = latest_commit
                if base_commit and latest_commit == base_commit:
                    checkpoint = None
                post.metadata["checkpoint"] = checkpoint
            except git.GitError:
                effective_status = RunStatus.failed
                finish_reason = "missing_checkpoint"
                error_message = (
                    "Run exited successfully but no valid checkpoint could be read"
                )
            else:
                if not post.metadata.get("checkpoint"):
                    effective_status = RunStatus.failed
                    finish_reason = "no_new_checkpoint"
                    error_message = (
                        "Run exited successfully but produced no new commit checkpoint"
                    )
        else:
            effective_status = RunStatus.failed
            finish_reason = "missing_worktree"
            error_message = "Run exited successfully but worktree no longer exists"

    post.metadata["status"] = effective_status.value
    if finish_reason:
        post.metadata["finish_reason"] = finish_reason
    if error_message:
        post.metadata["error_message"] = error_message
    elif effective_status == RunStatus.failed:
        log_tail = _read_run_log_tail(_run_log_file_for_run_file(latest_file))
        if log_tail:
            post.metadata["error_message"] = log_tail

    latest_file.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")

    if effective_status in (RunStatus.failed, RunStatus.timed_out):
        _terminate_active_run(
            {
                "agent_pid": runtime.get("agent_pid") or post.metadata.get("pid"),
                "pid": runtime.get("agent_pid") or post.metadata.get("pid"),
                "launcher_pid": runtime.get("launcher_pid")
                or post.metadata.get("launcher_pid"),
                "pgid": runtime.get("pgid") or post.metadata.get("pgid"),
            }
        )

    worktree_path = project_path / "worktrees" / task_name
    if worktree_path.exists():
        _run_hook(project_path, "after_run", worktree_path)

    final_error_message = post.metadata.get("error_message")

    if effective_status in (RunStatus.failed, RunStatus.timed_out):
        update_task_status(project_path, task_name, TaskStatus.failed)
        set_task_feedback(
            project_path,
            task_name,
            "failed",
            final_error_message
            if isinstance(final_error_message, str) and final_error_message.strip()
            else f"Task failed ({effective_status.value}).",
        )
    elif effective_status == RunStatus.completed:
        if is_task_auto_managed(project_path, task_name):
            update_task_status(project_path, task_name, TaskStatus.done)
            set_task_feedback(project_path, task_name, "completed", "Task completed successfully.")
        else:
            update_task_status(project_path, task_name, TaskStatus.pending)
            set_task_feedback(
                project_path,
                task_name,
                "completed",
                "Run completed successfully. Task is pending next action.",
            )
    elif effective_status == RunStatus.stopped:
        update_task_status(project_path, task_name, TaskStatus.pending)
        set_task_feedback(project_path, task_name, "stopped", "Run stopped by operator.")

    return effective_status


def list_runs(project_path: Path) -> list[dict]:
    """List running runs across tasks in a project."""
    runs: list[dict] = []
    task_root = config.tasks_dir(project_path)
    if not task_root.exists():
        return runs

    for item in sorted(task_root.iterdir()):
        if item.name == config.ARCHIVE_DIR or not item.is_dir():
            continue
        task_name = item.name
        active = get_active_run(project_path, task_name)
        if active:
            active["task"] = task_name
            runs.append(active)
    return runs


def _run_files(project_path: Path, task_name: str) -> list[Path]:
    run_dir = config.runs_dir(project_path, task_name)
    if run_dir.exists():
        return sorted(run_dir.glob("*.md"))
    return []


def _checkout_task_branch(project_path: Path, worktree_path: Path, branch: str) -> None:
    attach_ref = None
    if not git.ref_exists(project_path, branch):
        attach_ref = git.get_main_branch(project_path)
    git.checkout_branch(worktree_path, branch, start_ref=attach_ref)


def _build_run_prompt(task_body: str) -> str:
    parts = [task_body.rstrip()]
    parts.append("")
    parts.append("## AGVV Runtime Notes")
    parts.append("- Python command compatibility: if `python` is unavailable, use `python3`.")
    return "\n".join(parts).strip() + "\n"


def _build_acpx_prompt_command(agent: str, prompt: str) -> list[str]:
    """Build an acpx one-shot prompt command."""
    acpx_bin, acpx_args = acpx_invocation()
    opts = acpx_opts()
    return [acpx_bin, *acpx_args, *opts, agent, prompt]


def _run_hook(project_path: Path, hook_name: str, worktree_path: Path) -> None:
    """Run a lifecycle hook if configured."""
    config_path = config.project_agvv_dir(project_path) / config.CONFIG_FILE
    if not config_path.exists():
        return

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid project config JSON ({config_path}): {e}") from e

    hooks = cfg.get("hooks", {}) if isinstance(cfg, dict) else {}
    if not hooks or hook_name not in hooks:
        return

    cmd = hooks[hook_name]
    if not isinstance(cmd, str) or not cmd.strip():
        return
    try:
        subprocess.run(
            cmd,
            shell=True,
            cwd=worktree_path,
            timeout=60,
            check=True,
            capture_output=True,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        if hook_name == "before_run":
            raise


def _runtime_file(project_path: Path, task_name: str, run_num: int) -> Path:
    return config.runs_dir(project_path, task_name) / f"{run_num:03d}.runtime.json"


def _runtime_file_for_run_file(run_file: Path) -> Path:
    return run_file.with_suffix(".runtime.json")


def _run_log_file(project_path: Path, task_name: str, run_num: int) -> Path:
    return config.runs_dir(project_path, task_name) / f"{run_num:03d}.log"


def _run_log_file_for_run_file(run_file: Path) -> Path:
    return run_file.with_suffix(".log")


def _wait_for_runtime_file(runtime_file: Path, timeout_s: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runtime = read_runtime_info(runtime_file)
        if runtime.get("pgid") or runtime.get("agent_pid"):
            return runtime
        time.sleep(0.05)
    return {}


def _read_run_log_tail(log_file: Path, max_chars: int = 2000) -> str | None:
    if not log_file.exists():
        return None
    try:
        content = log_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not content:
        return None
    if len(content) > max_chars:
        content = content[-max_chars:]
    return content


def _kill_active_process_group(active: dict, sig: int) -> None:
    pgid = active.get("pgid")
    pid = active.get("pid") or active.get("launcher_pid")
    try:
        if pgid:
            os.killpg(pgid, sig)
        elif pid:
            os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_active_run(active: dict) -> bool:
    monitor_pid = active.get("agent_pid") or active.get("pid")
    launcher_pid = active.get("launcher_pid")
    pgid = active.get("pgid")
    if not process_alive(monitor_pid) and not process_alive(launcher_pid):
        return True

    if pgid:
        has_tracked_member = False
        for pid in (monitor_pid, launcher_pid):
            if not process_alive(pid):
                continue
            try:
                if os.getpgid(pid) == pgid:
                    has_tracked_member = True
                    break
            except (ProcessLookupError, PermissionError):
                continue
        if not has_tracked_member:
            pgid = None
            active = dict(active)
            active["pgid"] = None

    for _ in range(20):
        if not process_alive(monitor_pid) and not process_alive(launcher_pid):
            break
        time.sleep(0.1)

    if process_alive(monitor_pid) or process_alive(launcher_pid):
        _kill_active_process_group(active, signal.SIGTERM)
        for _ in range(30):
            if not process_alive(monitor_pid) and not process_alive(launcher_pid):
                break
            time.sleep(0.1)

    if process_alive(monitor_pid) or process_alive(launcher_pid):
        _kill_active_process_group(active, signal.SIGKILL)
        for _ in range(20):
            if not process_alive(monitor_pid) and not process_alive(launcher_pid):
                break
            time.sleep(0.1)

    for _ in range(20):
        if not process_alive(monitor_pid) and not process_alive(launcher_pid):
            return True
        time.sleep(0.1)

    return not process_alive(monitor_pid) and not process_alive(launcher_pid)
