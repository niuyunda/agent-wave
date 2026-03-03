"""Project command handlers extracted from CLI presentation wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from agvv.commands.contracts import AdoptProjectFn, InitProjectFn


def execute_project_init(
    *,
    project_name: str,
    base_dir: str | None,
    init_project: InitProjectFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Initialize a project layout and return one output line."""

    resolved_base_dir = resolve_optional_path(base_dir) or Path.cwd()
    paths = init_project(project_name=project_name, base_dir=resolved_base_dir)
    return (
        f"Project initialized: {project_name}\t"
        f"repo={paths.repo_dir}\tmain={paths.main_dir}"
    )


def execute_project_adopt(
    *,
    existing_repo: str,
    project_name: str,
    base_dir: str | None,
    adopt_project: AdoptProjectFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Adopt an existing repository and return one output line."""

    resolved_base_dir = resolve_optional_path(base_dir) or Path.cwd()
    paths, branch = adopt_project(
        existing_repo=Path(existing_repo).expanduser().resolve(),
        project_name=project_name,
        base_dir=resolved_base_dir,
    )
    return (
        f"Project adopted: {project_name}\tbranch={branch}\t"
        f"repo={paths.repo_dir}\tmain={paths.main_dir}"
    )
