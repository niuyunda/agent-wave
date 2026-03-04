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
) -> TaskSpec:
    """Apply CLI ``--agent`` override to spec."""

    if agent_provider is None:
        return spec

    provider = normalize_agent_provider(agent_provider or spec.agent or "codex")
    model = spec.agent_model
    extra_args = list(spec.agent_extra_args or [])
    agent_cmd = build_agent_command(provider=provider, model=model, extra_args=extra_args)
    return replace(spec, agent=provider, agent_model=model, agent_cmd=agent_cmd, agent_extra_args=extra_args)


def run_task_from_spec(
    spec_path: Path,
    db_path: Path | None = None,
    *,
    agent_provider: str | None = None,
    project_dir: Path | None = None,
    orchestration_port: OrchestrationPort | None = None,
) -> TaskSnapshot:
    """Create task from spec and start coding session."""

    spec = load_task_spec(spec_path)
    spec = _apply_agent_overrides(spec, agent_provider=agent_provider)
    port = resolve_orchestration_port(orchestration_port)

    if project_dir is not None:
        source_repo = project_dir.expanduser().resolve()
        if not source_repo.exists():
            raise AgvvError(f"Project directory not found: {source_repo}")
        layout = port.layout_paths(spec.project_name, spec.base_dir)
        if not layout.repo_dir.exists() or not layout.main_dir.exists():
            port.adopt_project(existing_repo=source_repo, project_name=spec.project_name, base_dir=spec.base_dir)
    else:
        layout = port.layout_paths(spec.project_name, spec.base_dir)
        if not layout.repo_dir.exists() or not layout.main_dir.exists():
            port.init_project(project_name=spec.project_name, base_dir=spec.base_dir)
    layout = port.layout_paths(spec.project_name, spec.base_dir)
    if not layout.repo_dir.exists():
        raise AgvvError(
            f"Project repository is not initialized at {layout.repo_dir}. "
            "Automatic project setup failed during task startup."
        )

    store = TaskStore(db_path)
    task = store.create_task(spec)
    return launch_coding_session(
        store,
        task,
        fresh_setup=True,
        orchestration_port=port,
    )
