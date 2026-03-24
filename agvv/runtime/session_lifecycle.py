"""Session and workspace lifecycle operations for runtime tasks."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import agvv.orchestration as orch
from agvv.runtime.models import TaskState, acp_agent_subcommand
from agvv.runtime.prompting import write_launch_artifacts
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.shared.errors import AgvvError


class LaunchArtifacts(TypedDict):
    """Paths to files written during agent session startup."""

    prompt_path: Path
    input_snapshot_path: Path
    output_log_path: Path


def start_acp_agent(
    store: TaskStore,
    task: TaskSnapshot,
    worktree: Path,
    *,
    event_step_prefix: str = "task.launch",
) -> LaunchArtifacts:
    """Start an acpx session running the coding agent.

    Creates the acpx session and sends the rendered prompt, blocking until
    the agent completes or the timeout is reached.  Raises on hard failures.
    """
    from agvv.orchestration import acp_ops
    from agvv.shared.errors import AgvvError as _AgvvError

    artifacts: LaunchArtifacts = write_launch_artifacts(
        worktree=worktree, spec=task.spec
    )

    session_name = task.session
    agent_subcmd = acp_agent_subcommand(task.agent or "codex")

    try:
        if not acp_ops.acpx_session_exists(agent_subcmd, session_name, worktree):
            acp_ops.acpx_create_session(agent_subcmd, session_name, worktree)
    except _AgvvError as exc:
        store.add_event(
            task.id,
            "warning",
            f"{event_step_prefix}.session_create",
            f"Failed to create acpx session: {exc}",
            {"session": session_name},
        )
        raise _AgvvError(f"Failed to create acpx session: {exc}") from exc

    timeout_seconds = task.spec.timeout_minutes * 60
    try:
        acp_ops.acpx_send_prompt(
            agent=agent_subcmd,
            session=session_name,
            cwd=worktree,
            prompt_path=artifacts["prompt_path"],
            output_log_path=artifacts["output_log_path"],
            timeout_seconds=timeout_seconds,
        )
    except _AgvvError as exc:
        store.add_event(
            task.id,
            "warning",
            f"{event_step_prefix}.prompt_error",
            f"Prompt send failed: {exc}",
            {"session": session_name},
        )
        raise

    return artifacts


def launch_coding_session(
    store: TaskStore,
    task: TaskSnapshot,
    *,
    fresh_setup: bool,
) -> TaskSnapshot:
    """Ensure feature worktree exists and launch acpx coding session."""
    launch_started_at = now_iso()
    try:
        worktree = feature_worktree_path(task)
        if fresh_setup:
            orch.start_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                from_branch=task.spec.from_branch,
                agent=task.agent,
                task_id=task.id,
                ticket=task.spec.ticket,
                params={},
            )

        if not worktree.exists():
            raise AgvvError(f"Feature worktree not found: {worktree}")
        artifacts = start_acp_agent(
            store, task, worktree, event_step_prefix="task.launch"
        )
    except Exception as exc:
        return mark_failed(
            store, task, "task.launch", f"Failed to launch coding session: {exc}"
        )

    from agvv.orchestration import acp_ops

    agent_subcmd = acp_agent_subcommand(task.agent or "codex")
    session_status = acp_ops.acpx_session_status(agent_subcmd, task.session, worktree)

    event_meta = {
        "session": task.session,
        "prompt_path": str(artifacts["prompt_path"]),
        "input_snapshot_path": str(artifacts["input_snapshot_path"]),
        "output_log_path": str(artifacts["output_log_path"]),
        "session_state": session_status.state,
    }

    # acpx prompt send waits for agent execution; if the session already ended,
    # persist terminal DONE immediately instead of waiting for daemon reconciliation.
    if session_status.state in ("dead", "no_session"):
        store.add_event(
            task.id, "info", "session.done", "Coding session ended", event_meta
        )
        return store.update_task(
            task.id,
            state=TaskState.DONE,
            started_at=launch_started_at,
            finished_at=now_iso(),
            last_error=None,
        )

    if session_status.state is None:
        store.add_event(
            task.id,
            "warning",
            "task.launch.status_unknown",
            "Coding session status is unknown; keeping task in RUNNING state.",
            event_meta,
        )
    else:
        store.add_event(
            task.id,
            "info",
            "task.launch",
            "Coding session started",
            event_meta,
        )

    return store.update_task(
        task.id,
        state=TaskState.RUNNING,
        started_at=launch_started_at,
        finished_at=None,
        last_error=None,
    )
