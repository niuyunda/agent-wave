"""Task creation and launch use case."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agvv.runtime.adapters import resolve_orchestration_port
from agvv.runtime.models import TaskSpec, build_agent_command, normalize_agent_provider
from agvv.runtime.ports import OrchestrationPort
from agvv.runtime.session_lifecycle import launch_coding_session
from agvv.runtime.spec import load_task_spec
from agvv.runtime.store import TaskSnapshot, TaskStore
from agvv.shared.errors import AgvvError


def _apply_agent_overrides(
    spec: TaskSpec,
    *,
    agent_provider: str | None = None,
    agent_model: str | None = None,
) -> TaskSpec:
    """Apply CLI ``--agent`` and ``--model`` overrides to spec."""

    if agent_provider is None and agent_model is None:
        return spec

    provider = normalize_agent_provider(agent_provider or spec.agent or "codex")
    model = spec.agent_model if agent_model is None else (agent_model.strip() or None)
    extra_args = list(spec.agent_extra_args or [])
    agent_cmd = build_agent_command(provider=provider, model=model, extra_args=extra_args)
    return replace(spec, agent=provider, agent_model=model, agent_cmd=agent_cmd, agent_extra_args=extra_args)


def run_task_from_spec(
    spec_path: Path,
    db_path: Path | None = None,
    *,
    agent_provider: str | None = None,
    agent_model: str | None = None,
    orchestration_port: OrchestrationPort | None = None,
) -> TaskSnapshot:
    """Create task from spec and start coding session."""

    spec = load_task_spec(spec_path)
    spec = _apply_agent_overrides(spec, agent_provider=agent_provider, agent_model=agent_model)
    port = resolve_orchestration_port(orchestration_port)
    layout = port.layout_paths(spec.project_name, spec.base_dir)
    if not layout.repo_dir.exists():
        raise AgvvError(
            f"Project repository is not initialized at {layout.repo_dir}. "
            f"Run `agvv project init {spec.project_name} --base-dir {spec.base_dir}` "
            "or `agvv project adopt ...` first, then configure remote before running tasks."
        )
    if not port.git_remote_exists(worktree=layout.repo_dir, remote=spec.branch_remote):
        raise AgvvError(
            f"No git remote '{spec.branch_remote}' configured for project '{spec.project_name}'. "
            f"Configure it with `git -C {layout.repo_dir} remote add {spec.branch_remote} <url>` "
            "before running tasks."
        )

    store = TaskStore(db_path)
    task = store.create_task(spec)
    return launch_coding_session(
        store,
        task,
        fresh_setup=True,
        orchestration_port=port,
    )
