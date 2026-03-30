"""Project management logic."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from agvv.core import config
from agvv.core.models import ProjectEntry


def _read_projects_file() -> list[ProjectEntry]:
    """Read the global projects registry."""
    pf = config.PROJECTS_FILE
    if not pf.exists():
        return []
    post = frontmatter.load(str(pf))
    entries = post.metadata.get("projects", [])
    if not entries:
        return []
    return [ProjectEntry(**e) for e in entries]


def _write_projects_file(entries: list[ProjectEntry]) -> None:
    """Write the global projects registry."""
    config.ensure_agvv_home()
    data = {"projects": [e.model_dump() for e in entries]}
    post = frontmatter.Post("", **data)
    config.PROJECTS_FILE.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def list_projects() -> list[ProjectEntry]:
    return _read_projects_file()


def add_project(path: Path) -> ProjectEntry:
    """Register a project. Initializes .agvv/ in the project."""
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")

    entries = _read_projects_file()
    for e in entries:
        if Path(e.path).resolve() == path:
            raise ValueError(f"Project already registered: {path}")

    # Initialize .agvv/ structure
    agvv_dir = config.project_agvv_dir(path)
    agvv_dir.mkdir(exist_ok=True)
    config.tasks_dir(path).mkdir(exist_ok=True)
    config.archive_dir(path).mkdir(exist_ok=True)

    # Create default config.md if not exists
    config_path = agvv_dir / config.CONFIG_FILE
    if not config_path.exists():
        config_path.write_text("---\n---\n", encoding="utf-8")

    entry = ProjectEntry(path=str(path))
    entries.append(entry)
    _write_projects_file(entries)
    return entry


def remove_project(path: Path) -> None:
    """Unregister a project (does not delete .agvv/)."""
    path = path.resolve()
    entries = _read_projects_file()
    new_entries = [e for e in entries if Path(e.path).resolve() != path]
    if len(new_entries) == len(entries):
        raise ValueError(f"Project not registered: {path}")
    _write_projects_file(new_entries)


def find_project_for_task(task_name: str) -> Path | None:
    """Find which project contains a given task."""
    for entry in _read_projects_file():
        project_path = Path(entry.path)
        if config.task_dir(project_path, task_name).is_dir():
            return project_path
    return None


def resolve_project(project: str | None, task_name: str | None = None) -> Path:
    """Resolve a project path from explicit arg or task-name lookup."""
    if project:
        return Path(project).resolve()
    if task_name:
        found = find_project_for_task(task_name)
        if found:
            return found
        raise ValueError(
            f"Cannot find task '{task_name}' in any registered project. "
            "Specify --project explicitly."
        )
    raise ValueError("--project is required")
