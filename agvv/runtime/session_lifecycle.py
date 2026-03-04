"""Session and workspace lifecycle operations for runtime tasks."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.adapters import DEFAULT_ORCHESTRATION_PORT as port
from agvv.runtime.models import TaskState
from agvv.runtime.prompting import agent_requires_tty, build_launch_command, write_launch_artifacts
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.shared.errors import AgvvError


def start_tmux_agent(
    store: TaskStore,
    task: TaskSnapshot,
    worktree: Path,
    *,
    event_step_prefix: str = "task.launch",
) -> dict[str, Path]:
    """Start a tmux session running the coding agent and capture output.

    Creates the tmux session, injects the prompt, and sets up pane logging
    when the agent requires a TTY.  Returns the artifact paths dict.

    Raises on hard failures so callers can handle errors consistently.
    """
    artifacts = write_launch_artifacts(worktree=worktree, spec=task.spec)
    launch_command = build_launch_command(
        spec=task.spec,
        prompt_path=artifacts["prompt_path"],
        output_log_path=artifacts["output_log_path"],
    )
    port.tmux_new_session(task.session, worktree, launch_command)

    if agent_requires_tty(task.spec):
        try:
            port.tmux_pipe_pane(task.session, artifacts["output_log_path"])
        except Exception as exc:
            store.add_event(
                task.id,
                "warning",
                f"{event_step_prefix}.log_capture",
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
        if port.tmux_session_exists(task.session):
            raise AgvvError(f"tmux session already exists: {task.session}")
        if fresh_setup:
            port.start_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                from_branch=task.spec.from_branch,
                agent=task.agent,
                task_id=task.id,
                ticket=task.spec.ticket,
                params={
                    **(task.spec.params or {}),
                    "task_doc": str(task.spec.task_doc) if task.spec.task_doc else "",
                },
                create_dirs=task.spec.create_dirs or [],
            )

        worktree = feature_worktree_path(task)
        if not worktree.exists():
            raise AgvvError(f"Feature worktree not found: {worktree}")
        artifacts = start_tmux_agent(store, task, worktree, event_step_prefix="task.launch")
    except Exception as exc:
        return mark_failed(store, task, "task.launch", f"Failed to launch coding session: {exc}")

    store.add_event(
        task.id,
        "info",
        "task.launch",
        "Coding session started",
        {
            "session": task.session,
            "prompt_path": str(artifacts["prompt_path"]),
            "input_snapshot_path": str(artifacts["input_snapshot_path"]),
            "output_log_path": str(artifacts["output_log_path"]),
        },
    )
    return store.update_task(
        task.id,
        state=TaskState.CODING,
        started_at=(task.started_at or now_iso()),
        finished_at=None,
        last_error=None,
    )
