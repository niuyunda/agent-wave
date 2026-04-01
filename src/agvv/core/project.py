"""Project management logic."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from agvv.core import config
from agvv.core.models import ProjectEntry
from agvv.utils import git


def _default_project_config(hooks_dir: Path) -> dict:
    hook_scripts = {
        "after_create": hooks_dir / "after_create.sh",
        "before_run": hooks_dir / "before_run.sh",
        "after_run": hooks_dir / "after_run.sh",
    }
    return {
        "agvv_repo": "https://github.com/niuyunda/agent-wave",
        "hooks": {
            name: f"bash {shlex.quote(str(path))}"
            for name, path in hook_scripts.items()
        },
    }


def _parse_projects_json(path: Path) -> list[ProjectEntry]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid projects registry JSON ({path.name}): {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Invalid projects registry: root must be an object ({path.name})")
    items = data.get("projects", [])
    if not isinstance(items, list):
        raise ValueError(f"Invalid projects registry: 'projects' must be a list ({path.name})")
    return [ProjectEntry(**e) for e in items]


def _read_projects_file() -> list[ProjectEntry]:
    """Read the global projects registry (JSON)."""
    pf = config.projects_registry_path()
    if not pf.exists():
        return []
    return _parse_projects_json(pf)


def _write_projects_file(entries: list[ProjectEntry]) -> None:
    """Write the global projects registry as JSON."""
    config.ensure_agvv_home()
    payload = {"projects": [e.model_dump() for e in entries]}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    config.projects_registry_path().write_text(text, encoding="utf-8")


def list_projects() -> list[ProjectEntry]:
    return _read_projects_file()


def _ensure_project_repo(path: Path) -> None:
    """Ensure the target directory is a Git repository with at least one commit."""
    if not git.is_git_repo(path):
        try:
            git.init_repo(path)
        except git.GitError as e:
            raise ValueError(f"Failed to initialize Git repository at {path}: {e}") from e

    if not git.has_commits(path):
        try:
            git.run_git(["add", "-A"], cwd=path)
            commit_args = ["commit", "-m", "agvv: init"]
            if not git.has_staged_changes(path):
                commit_args.insert(1, "--allow-empty")
            git.run_git(commit_args, cwd=path)
        except git.GitError as e:
            raise ValueError(
                "Git repository needs an initial commit before agvv can use worktrees. "
                "Configure git user.name/user.email or create the first commit manually."
            ) from e


def _ensure_project_layout(path: Path) -> None:
    """Ensure agvv project metadata exists in ``.agvv/``."""
    agvv_dir = config.project_agvv_dir(path)
    agvv_dir.mkdir(exist_ok=True)
    config.tasks_dir(path).mkdir(exist_ok=True)
    config.archive_dir(path).mkdir(exist_ok=True)

    hooks_dir = agvv_dir / config.HOOKS_DIR
    hooks_dir.mkdir(exist_ok=True)
    for hook_name in ("after_create", "before_run", "after_run"):
        hook_path = hooks_dir / f"{hook_name}.sh"
        if not hook_path.exists():
            hook_path.write_text("", encoding="utf-8")

    config_path = agvv_dir / config.CONFIG_FILE
    if not config_path.exists():
        payload = _default_project_config(hooks_dir)
        config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_project(path: Path) -> ProjectEntry:
    """Ensure a project is initialized and present in the global registry."""
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")

    _ensure_project_repo(path)
    _ensure_project_layout(path)

    entries = _read_projects_file()
    for e in entries:
        if Path(e.path).resolve() == path:
            return e

    entry = ProjectEntry(path=str(path))
    entries.append(entry)
    _write_projects_file(entries)
    return entry


def add_project(path: Path) -> ProjectEntry:
    """Register a project. Initializes .agvv/ in the project."""
    path = path.resolve()
    if not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")

    for e in _read_projects_file():
        if Path(e.path).resolve() == path:
            raise ValueError(f"Project already registered: {path}")

    return ensure_project(path)


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
