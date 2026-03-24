"""Core task use-case entrypoints: run, retry, cleanup, query."""

from __future__ import annotations

import shutil
from pathlib import Path

import agvv.orchestration as orch
from agvv.runtime.models import (
    RECOVERABLE_RETRY_STATES,
    TaskSpec,
    TaskState,
    normalize_agent_provider,
    build_agent_command,
    acp_agent_subcommand,
)
from agvv.orchestration import acp_ops
from agvv.runtime.session_lifecycle import launch_coding_session
from agvv.runtime.spec import load_task_spec
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed
from agvv.shared.errors import AgvvError


def _apply_agent_overrides(
    spec: TaskSpec,
    *,
    agent_provider: str | None = None,
) -> TaskSpec:
    """Apply CLI --agent override to spec."""
    if agent_provider is None:
        return spec
    provider = normalize_agent_provider(agent_provider or spec.agent or "codex")
    model = spec.agent_model
    extra_args = list(spec.agent_extra_args or [])
    agent_cmd = build_agent_command(
        provider=provider, model=model, extra_args=extra_args
    )
    return spec.model_copy(
        update={
            "agent": provider,
            "agent_model": model,
            "agent_cmd": agent_cmd,
            "agent_extra_args": extra_args,
        }
    )


def _resolve_runtime_base_dir(*, project_dir: Path | None) -> Path:
    """Resolve runtime base directory: parent of project_dir, or cwd."""
    if project_dir is None:
        return Path.cwd().resolve()
    return project_dir.expanduser().resolve().parent


def run_task_from_spec(
    spec_path: Path,
    db_path: Path | None = None,
    *,
    agent_provider: str | None = None,
    project_dir: Path | None = None,
) -> TaskSnapshot:
    """Create task from spec and start coding session."""
    spec = load_task_spec(spec_path)
    spec = _apply_agent_overrides(
        spec,
        agent_provider=agent_provider,
    )
    resolved_base_dir = _resolve_runtime_base_dir(project_dir=project_dir)
    spec = spec.model_copy(update={"base_dir": resolved_base_dir})

    if project_dir is not None:
        source_repo = project_dir.expanduser().resolve()
        layout = orch.layout_paths(spec.project_name, spec.base_dir)
        if source_repo.exists():
            # --dir points to an existing directory: adopt it.
            if not layout.repo_dir.exists() or not layout.main_dir.exists():
                orch.adopt_project(
                    existing_repo=source_repo,
                    project_name=spec.project_name,
                    base_dir=spec.base_dir,
                )
        else:
            # --dir points to a non-existent path: create the project there.
            if not layout.repo_dir.exists() or not layout.main_dir.exists():
                orch.init_project(
                    project_name=spec.project_name,
                    base_dir=spec.base_dir,
                )
    else:
        layout = orch.layout_paths(spec.project_name, spec.base_dir)
        if not layout.repo_dir.exists() or not layout.main_dir.exists():
            orch.init_project(project_name=spec.project_name, base_dir=spec.base_dir)

    layout = orch.layout_paths(spec.project_name, spec.base_dir)
    if not layout.repo_dir.exists():
        raise AgvvError(
            f"Project repository is not initialized at {layout.repo_dir}. "
            "Automatic project setup failed during task startup."
        )

    # Copy task spec into docs/ so it becomes part of the project git history.
    # Skip if the spec is already inside the project directory.
    # Idempotent: only copy if docs/ was created by init_project/adopt_project.
    project_root = layout.docs_dir.parent.resolve()
    if not str(spec_path.resolve()).startswith(str(project_root) + "/"):
        dest = layout.docs_dir / spec_path.name
        try:
            layout.docs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(spec_path.resolve(), dest)
        except OSError:
            # docs/ not available yet (e.g. tests with mocked init); skip gracefully.
            pass

    store = TaskStore(db_path)
    task = store.create_task(spec)
    return launch_coding_session(store, task, fresh_setup=True)


def retry_task(
    task_id: str,
    db_path: Path | None = None,
    session: str | None = None,
    *,
    force_restart: bool = False,
) -> TaskSnapshot:
    """Retry task from recoverable states and relaunch coding session."""
    store = TaskStore(db_path)
    task = store.get_task(task_id)

    if task.state not in RECOVERABLE_RETRY_STATES:
        raise AgvvError(f"Cannot retry task in state: {task.state.value}")

    worktree = feature_worktree_path(task)
    agent_subcmd = acp_agent_subcommand(task.agent or "codex")
    session_exists = acp_ops.acpx_session_exists(agent_subcmd, task.session, worktree)
    if session_exists and not force_restart:
        raise AgvvError(f"Task is already running in session: {task.session}")
    if session_exists and force_restart:
        acp_ops.acpx_delete_session(agent_subcmd, task.session, worktree)
        store.add_event(
            task.id,
            "warning",
            "task.retry.force_restart",
            "Deleted existing acpx session before retry relaunch.",
            {"session": task.session, "state": task.state.value},
        )

    if session and session != task.session:
        store.add_event(
            task.id,
            "info",
            "task.retry",
            "Session override requested",
            {"session": session},
        )
        task = store.update_task_session(task.id, session)
        worktree = feature_worktree_path(task)

    return launch_coding_session(store, task, fresh_setup=not worktree.exists())


def cleanup_task(
    task_id: str,
    db_path: Path | None = None,
    force: bool = False,
) -> TaskSnapshot:
    """Cleanup task resources and transition to CLEANED."""
    store = TaskStore(db_path)
    task = store.get_task(task_id)

    try:
        worktree = feature_worktree_path(task)
        agent_subcmd = acp_agent_subcommand(task.agent or "codex")
        # Hard-delete the acpx session: close it and remove its files.
        # Safe to call even if the session already finished or the worktree is gone.
        acp_ops.acpx_delete_session(agent_subcmd, task.session, worktree)

        if force:
            orch.cleanup_feature_force(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                delete_branch=True,
            )
        else:
            orch.cleanup_feature(
                project_name=task.project_name,
                feature=task.feature,
                base_dir=task.spec.base_dir,
                delete_branch=True,
            )
    except Exception as exc:
        return mark_failed(store, task, "task.cleanup", f"Cleanup failed: {exc}")

    store.add_event(task.id, "info", "task.cleanup", "Task resources cleaned")
    return store.update_task(task.id, state=TaskState.CLEANED, finished_at=now_iso())


def list_task_statuses(
    db_path: Path | None = None,
    state: TaskState | None = None,
) -> list[TaskSnapshot]:
    """List runtime tasks sorted by update time."""
    return TaskStore(db_path).list_tasks(state=state)
