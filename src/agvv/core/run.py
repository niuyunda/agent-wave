"""Run management logic."""

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
from agvv.core.models import RunMeta, RunPurpose, RunStatus, TaskStatus
from agvv.core.session import ensure_session
from agvv.core.task import next_run_number, update_task_status
from agvv.utils import git, markdown

_TERMINAL_RUNTIME_STATUSES = {"finished", "failed", "completed", "stopped"}


def start_run(
    project_path: Path,
    task_name: str,
    purpose: RunPurpose,
    agent: str,
    base_branch: str | None = None,
) -> RunMeta:
    """Start a new run for a task."""
    # Check authentication before starting
    auth_warning = check_acpx_auth()
    if auth_warning:
        import warnings
        warnings.warn(auth_warning)

    task_file = config.task_file(project_path, task_name)
    if not task_file.exists():
        raise ValueError(f"Task '{task_name}' not found")

    # Check no run is already active for this task
    active = get_active_run(project_path, task_name)
    if active:
        raise ValueError(
            f"Task '{task_name}' already has an active run (PID {active.get('pid')})"
        )

    branch = f"{config.BRANCH_PREFIX}{task_name}"
    run_num = next_run_number(project_path, task_name)
    worktree_path = project_path / "worktrees" / task_name
    worktree_ref, detached_mode = _resolve_worktree_ref(
        project_path,
        task_name,
        purpose,
        base_branch,
    )

    # Create worktree if needed
    worktree_created = False
    if not worktree_path.exists():
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if detached_mode:
            git.create_detached_worktree(project_path, worktree_path, worktree_ref)
        else:
            git.create_worktree(project_path, worktree_path, branch)
        worktree_created = True
        _run_hook(project_path, "after_create", worktree_path)
    elif detached_mode:
        try:
            git.checkout_detached(worktree_path, worktree_ref)
        except git.GitError as e:
            raise ValueError(
                f"Failed to switch worktree '{task_name}' to ref '{worktree_ref}': {e}"
            ) from e

    # Run before_run hook — on failure, clean up freshly created worktree
    try:
        _run_hook(project_path, "before_run", worktree_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if worktree_created:
            try:
                git.remove_worktree(project_path, worktree_path)
            except git.GitError:
                pass
        raise ValueError(f"before_run hook failed: {e}") from e

    # Read task description for prompt
    task_post = frontmatter.load(str(task_file))
    report_path = _default_report_path(task_name, run_num, purpose)
    prompt = _build_run_prompt(task_post.content, purpose, report_path)

    # Ensure a persistent acpx session exists for this task.
    # The session is scoped to (agent, worktree cwd, task name) and will be
    # reused across runs so the agent retains conversation context.
    ensure_session(project_path, task_name, agent)

    base_commit = None
    try:
        base_commit = git.get_latest_commit(worktree_path)
    except git.GitError:
        pass

    # Launch the real agent under a tiny Python runner that records runtime
    # facts in a sidecar JSON file. The daemon should track the actual agent
    # child PID / process group rather than a transient shell wrapper.
    session_name = task_name
    agent_cmd = _build_acpx_prompt_command(agent, session_name, prompt)
    runtime_file = _runtime_file(project_path, task_name, run_num, purpose)
    log_file = _run_log_file(project_path, task_name, run_num, purpose)
    runtime_env = os.environ.copy()
    runtime_env["AGVV_RUN_PURPOSE"] = purpose.value
    runtime_env["AGVV_TASK_NAME"] = task_name
    runtime_env["AGVV_RUN_AGENT"] = agent
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

    # Record run
    meta = RunMeta(
        purpose=purpose,
        agent=agent,
        pid=runtime.get("agent_pid") or proc.pid,
        launcher_pid=proc.pid,
        pgid=runtime.get("pgid"),
        base_branch=worktree_ref if detached_mode else branch,
        base_commit=base_commit,
        report_path=report_path,
    )
    run_file = config.runs_dir(project_path, task_name) / f"{run_num:03d}-{purpose.value}.md"
    markdown.write_md(run_file, meta.model_dump(mode="json"), "")

    # Update task status
    update_task_status(project_path, task_name, TaskStatus.running)
    return meta


def stop_run(project_path: Path, task_name: str) -> None:
    """Stop the active run for a task."""
    active = get_active_run(project_path, task_name)
    if not active:
        raise ValueError(f"No active run for task '{task_name}'")

    agent = active.get("agent", "codex")
    session_name = task_name

    # Try acpx cooperative cancel first, but do not trust it blindly. The run
    # is only stopped once the underlying process group is actually gone.
    cancel_cmd = _build_acpx_cancel_command(agent, session_name)
    try:
        subprocess.run(
            cancel_cmd,
            timeout=10,
            capture_output=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

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
        _finish_run(project_path, task_name, _status_from_runtime(latest))
        return None

    monitor_pid = latest.get("agent_pid") or latest.get("pid")
    if monitor_pid and not _process_alive(monitor_pid):
        _finish_run(project_path, task_name, _status_from_runtime(latest))
        return None
    return latest


def get_latest_run(project_path: Path, task_name: str) -> dict | None:
    """Get the latest run record with runtime details if available."""
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return None

    run_files = sorted(rd.glob("*.md"))
    if not run_files:
        return None

    latest = markdown.read_frontmatter(run_files[-1])
    latest["_task_status"] = latest.get("status")
    if latest["_task_status"] == RunStatus.running.value:
        latest.update(_read_runtime_info(_runtime_file_for_run_file(run_files[-1])))
    latest["_file"] = run_files[-1]
    return latest


def finish_run(project_path: Path, task_name: str, status: RunStatus) -> RunStatus | None:
    """Mark the active run as finished with given status."""
    return _finish_run(project_path, task_name, status)


def _finish_run(project_path: Path, task_name: str, status: RunStatus) -> RunStatus | None:
    """Internal: update the latest run record to finished."""
    rd = config.runs_dir(project_path, task_name)
    run_files = sorted(rd.glob("*.md"))
    if not run_files:
        return None

    latest_file = run_files[-1]
    post = frontmatter.load(str(latest_file))
    runtime = _read_runtime_info(_runtime_file_for_run_file(latest_file))

    effective_status = status
    finish_reason = None
    error_message = None

    exit_code = runtime.get("exit_code")
    if exit_code is not None:
        post.metadata["exit_code"] = exit_code

    post.metadata["status"] = status.value
    post.metadata["finished_at"] = runtime.get("finished_at") or datetime.now().isoformat(timespec="seconds")
    if runtime.get("launcher_pid") and not post.metadata.get("launcher_pid"):
        post.metadata["launcher_pid"] = runtime["launcher_pid"]
    if runtime.get("pgid") and not post.metadata.get("pgid"):
        post.metadata["pgid"] = runtime["pgid"]
    if runtime.get("agent_pid"):
        post.metadata["pid"] = runtime["agent_pid"]

    purpose = _parse_run_purpose(post.metadata.get("purpose"))
    base_commit = post.metadata.get("base_commit")

    # Capture checkpoint / artifacts if completed
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
                error_message = "Run exited successfully but no valid checkpoint could be read"
            else:
                if purpose in {RunPurpose.implement, RunPurpose.repair} and not post.metadata.get("checkpoint"):
                    effective_status = RunStatus.failed
                    finish_reason = "no_new_checkpoint"
                    error_message = "Run exited successfully but produced no new commit checkpoint"
                if purpose == RunPurpose.review:
                    report_path = post.metadata.get("report_path")
                    if not _review_report_exists(worktree_path, report_path):
                        effective_status = RunStatus.failed
                        finish_reason = "missing_review_report"
                        error_message = (
                            "Review run exited successfully but review report was not written"
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

    if effective_status in (RunStatus.failed, RunStatus.timed_out, RunStatus.stalled):
        _terminate_active_run(
            {
                "agent_pid": runtime.get("agent_pid") or post.metadata.get("pid"),
                "pid": runtime.get("agent_pid") or post.metadata.get("pid"),
                "launcher_pid": runtime.get("launcher_pid") or post.metadata.get("launcher_pid"),
                "pgid": runtime.get("pgid") or post.metadata.get("pgid"),
            }
        )

    # Run after_run hook
    worktree_path = project_path / "worktrees" / task_name
    if worktree_path.exists():
        _run_hook(project_path, "after_run", worktree_path)

    # Update task status based on run result
    if effective_status in (RunStatus.failed, RunStatus.timed_out, RunStatus.stalled):
        update_task_status(project_path, task_name, TaskStatus.failed)
    elif effective_status in (RunStatus.completed,):
        # After a run completes, task goes back to pending (awaiting next action)
        update_task_status(project_path, task_name, TaskStatus.pending)
    elif effective_status == RunStatus.stopped:
        update_task_status(project_path, task_name, TaskStatus.pending)

    return effective_status


def list_runs(project_path: Path) -> list[dict]:
    """List all active runs across all tasks in a project."""
    runs = []
    td = config.tasks_dir(project_path)
    if not td.exists():
        return runs

    for item in sorted(td.iterdir()):
        if item.name == config.ARCHIVE_DIR or not item.is_dir():
            continue
        task_name = item.name
        active = get_active_run(project_path, task_name)
        if active:
            active["task"] = task_name
            runs.append(active)
    return runs


def _resolve_worktree_ref(
    project_path: Path,
    task_name: str,
    purpose: RunPurpose,
    base_branch: str | None,
) -> tuple[str, bool]:
    """Resolve the ref to attach the worktree to.

    Returns (ref, detached_mode).
    """
    task_branch = f"{config.BRANCH_PREFIX}{task_name}"
    if purpose in {RunPurpose.review, RunPurpose.test}:
        if base_branch:
            if not git.ref_exists(project_path, base_branch):
                raise ValueError(f"Base branch/ref does not exist: {base_branch}")
            return base_branch, True
        if git.ref_exists(project_path, task_branch):
            return task_branch, True
        return git.get_main_branch(project_path), True
    return task_branch, False


def _default_report_path(task_name: str, run_num: int, purpose: RunPurpose) -> str | None:
    if purpose != RunPurpose.review:
        return None
    return f"reports/agvv/{task_name}/{run_num:03d}-{purpose.value}.md"


def _build_run_prompt(task_body: str, purpose: RunPurpose, report_path: str | None) -> str:
    parts = [task_body.rstrip()]
    parts.append("")
    parts.append("## AGVV Runtime Notes")
    parts.append("- Python command compatibility: if `python` is unavailable, use `python3`.")
    if purpose == RunPurpose.review and report_path:
        parts.append(f"- AGVV_REPORT_PATH={report_path}")
        parts.append(
            "- Write your review report to the AGVV_REPORT_PATH file before you finish."
        )
    return "\n".join(parts).strip() + "\n"


def _parse_run_purpose(raw_purpose: object) -> RunPurpose | None:
    if not isinstance(raw_purpose, str):
        return None
    try:
        return RunPurpose(raw_purpose)
    except ValueError:
        return None


def _review_report_exists(worktree_path: Path, report_path: object) -> bool:
    if not isinstance(report_path, str) or not report_path.strip():
        return False
    target = worktree_path / report_path
    if not target.exists() or not target.is_file():
        return False
    try:
        return bool(target.read_text(encoding="utf-8").strip())
    except OSError:
        return False



def _build_acpx_prompt_command(agent: str, session_name: str, prompt: str) -> list[str]:
    """Build an acpx command to send a prompt to a persistent session.

    Uses the session-based prompt flow instead of one-shot exec. The session
    must already exist (created via ensure_session). The agent retains
    conversation context across prompts within the same session.

    Environment variables:
        AGVV_ACPX_OPTS: Additional options for acpx (e.g., --approve-all, --model gpt-5.4)
        Note: Options like --approve-all must come BEFORE the agent name.
    """
    acpx_bin, acpx_args = acpx_invocation()
    opts = acpx_opts()

    return [acpx_bin, *acpx_args, *opts, agent, "-s", session_name, prompt]


def _build_acpx_cancel_command(agent: str, session_name: str) -> list[str]:
    """Build an acpx cancel command for the session."""
    acpx_bin, acpx_args = acpx_invocation()
    return [acpx_bin, *acpx_args, agent, "-s", session_name, "cancel"]


def _run_hook(project_path: Path, hook_name: str, worktree_path: Path) -> None:
    """Run a lifecycle hook if configured."""
    config_path = config.project_agvv_dir(project_path) / config.CONFIG_FILE
    if not config_path.exists():
        return

    post = frontmatter.load(str(config_path))
    hooks = post.metadata.get("hooks", {})
    if not hooks or hook_name not in hooks:
        return

    cmd = hooks[hook_name]
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
        # before_run failure should abort, others just log
        if hook_name == "before_run":
            raise


def _runtime_file(project_path: Path, task_name: str, run_num: int, purpose: RunPurpose) -> Path:
    return config.runs_dir(project_path, task_name) / f"{run_num:03d}-{purpose.value}.runtime.json"


def _runtime_file_for_run_file(run_file: Path) -> Path:
    return run_file.with_suffix(".runtime.json")


def _run_log_file(project_path: Path, task_name: str, run_num: int, purpose: RunPurpose) -> Path:
    return config.runs_dir(project_path, task_name) / f"{run_num:03d}-{purpose.value}.log"


def _run_log_file_for_run_file(run_file: Path) -> Path:
    return run_file.with_suffix(".log")


def _read_runtime_info(runtime_file: Path) -> dict:
    if not runtime_file.exists():
        return {}
    try:
        return json.loads(runtime_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _status_from_runtime(runtime_or_latest: dict) -> RunStatus:
    """Infer terminal run status from runtime-side fields."""
    runtime_status = runtime_or_latest.get("status")
    if runtime_status == RunStatus.stopped.value:
        return RunStatus.stopped

    exit_code = runtime_or_latest.get("exit_code")
    if exit_code is None:
        return RunStatus.failed

    try:
        return RunStatus.completed if int(exit_code) == 0 else RunStatus.failed
    except (ValueError, TypeError):
        return RunStatus.failed


def _wait_for_runtime_file(runtime_file: Path, timeout_s: float = 1.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runtime = _read_runtime_info(runtime_file)
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


def _process_alive(pid: int | None) -> bool:
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
    if not _process_alive(monitor_pid) and not _process_alive(launcher_pid):
        return True

    # Avoid signaling a recycled process-group id when no tracked member still
    # belongs to that pgid.
    if pgid:
        has_tracked_member = False
        for pid in (monitor_pid, launcher_pid):
            if not _process_alive(pid):
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
        if not _process_alive(monitor_pid) and not _process_alive(launcher_pid):
            break
        time.sleep(0.1)

    if _process_alive(monitor_pid) or _process_alive(launcher_pid):
        _kill_active_process_group(active, signal.SIGTERM)
        for _ in range(30):
            if not _process_alive(monitor_pid) and not _process_alive(launcher_pid):
                break
            time.sleep(0.1)

    if _process_alive(monitor_pid) or _process_alive(launcher_pid):
        _kill_active_process_group(active, signal.SIGKILL)
        for _ in range(20):
            if not _process_alive(monitor_pid) and not _process_alive(launcher_pid):
                break
            time.sleep(0.1)

    for _ in range(20):
        if not _process_alive(monitor_pid) and not _process_alive(launcher_pid):
            return True
        time.sleep(0.1)

    return not _process_alive(monitor_pid) and not _process_alive(launcher_pid)
