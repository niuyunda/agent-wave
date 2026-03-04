"""Project command handlers extracted from CLI presentation wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from agvv.commands.contracts import AdoptProjectFn, InitProjectFn


def execute_project_init(
    *,
    project_name: str,
    base_dir: str,
    init_project: InitProjectFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Initialize project layout and return one output line."""

    resolved_base_dir = resolve_optional_path(base_dir)
    if resolved_base_dir is None:
        raise RuntimeError("base_dir resolution unexpectedly returned None.")
    paths = init_project(project_name=project_name, base_dir=resolved_base_dir)
    return f"Project initialized: {project_name}\trepo={paths.repo_dir}\tmain={paths.main_dir}"


def execute_project_adopt(
    *,
    project_name: str,
    repo: str,
    base_dir: str,
    adopt_project: AdoptProjectFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Adopt project layout and return one output line."""

    resolved_repo = resolve_optional_path(repo)
    resolved_base_dir = resolve_optional_path(base_dir)
    if resolved_repo is None or resolved_base_dir is None:
        raise RuntimeError("path resolution unexpectedly returned None.")
    paths, branch = adopt_project(existing_repo=resolved_repo, project_name=project_name, base_dir=resolved_base_dir)
    return f"Project adopted: {project_name}\tbranch={branch}\trepo={paths.repo_dir}\tmain={paths.main_dir}"
