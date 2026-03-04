"""Session and workspace lifecycle operations for runtime tasks."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import agvv.orchestration as orch
from agvv.runtime.models import TaskState
from agvv.runtime.prompting import agent_requires_tty, build_launch_command, write_launch_artifacts
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.shared.errors import AgvvError


class LaunchArtifacts(TypedDict):
    """Paths to files written during agent session startup."""

    prompt_path: Path
    input_snapshot_path: Path
    output_log_path: Path


def start_tmux_agent(
    store: TaskStore,
    task: TaskSnapshot,
    worktree: Path,
    *,
    event_step_prefix: str = "task.launch",
) -> LaunchArtifacts:
    """Start a tmux session running the coding agent.

    Creates the tmux session, injects the rendered prompt, and sets up pane
    logging when the agent requires a TTY.  Raises on hard failures.
    """
    artifacts: LaunchArtifacts = write_launch_artifacts(worktree=worktree, spec=task.spec)
    launch_command = build_launch_command(
        spec=task.spec,
        prompt_path=artifacts["prompt_path"],
        output_log_path=artifacts["output_log_path"],
    )
    orch.tmux_new_session(task.session, worktree, launch_command)

    if agent_requires_tty(task.spec):
        try:
            orch.tmux_pipe_pane(task.session, artifacts["output_log_path"])
        except Exception as exc:
            store.add_event(
                task.id, "warning", f"{event_step_prefix}.log_capture",
                f"Failed to enable tmux pane log capture: {exc}",
                {"session": task.session, "output_log_path": str(artifacts["output_log_path"])},
            )
    return artifacts


def launch_coding_session(
    store: TaskStore,
    task: TaskSnapshot,
    *,
    fresh_setup: bool,
) -> TaskSnapshot:
    """Ensure feature worktree exists and launch tmux coding session."""
    try:
        if orch.tmux_session_exists(task.session):
            raise AgvvError(f"tmux session already exists: {task.session}")
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

        worktree = feature_worktree_path(task)
        if not worktree.exists():
            raise AgvvError(f"Feature worktree not found: {worktree}")
        artifacts = start_tmux_agent(store, task, worktree, event_step_prefix="task.launch")
    except Exception as exc:
        return mark_failed(store, task, "task.launch", f"Failed to launch coding session: {exc}")

    store.add_event(
        task.id, "info", "task.launch", "Coding session started",
        {
            "session": task.session,
            "prompt_path": str(artifacts["prompt_path"]),
            "input_snapshot_path": str(artifacts["input_snapshot_path"]),
            "output_log_path": str(artifacts["output_log_path"]),
        },
    )
    return store.update_task(
        task.id,
        state=TaskState.RUNNING,
        started_at=(task.started_at or now_iso()),
        finished_at=None,
        last_error=None,
    )
