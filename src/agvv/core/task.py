"""Task management logic."""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import frontmatter

from agvv.core import config
from agvv.core.models import RunMeta, RunStatus, TaskMeta, TaskStatus
from agvv.core.session import close_session
from agvv.utils import git, markdown


def validate_task_name(name: str) -> None:
    if not re.match(config.TASK_NAME_PATTERN, name):
        raise ValueError(
            f"Invalid task name '{name}'. Only [A-Za-z0-9._-] allowed."
        )


def add_task(project_path: Path, task_file_path: Path) -> str:
    """Add a task to a project from a task.md file. Returns task name."""
    post = frontmatter.load(str(task_file_path))
    name = post.metadata.get("name")
    if not name:
        raise ValueError("task.md must have 'name' in front matter")

    validate_task_name(name)

    td = config.task_dir(project_path, name)
    if td.exists():
        raise ValueError(
            f'task "{name}" already exists in project {project_path.name}'
        )

    # Create task directory and write task.md with agvv-managed fields
    meta = TaskMeta(name=name)
    tf = config.task_file(project_path, name)
    markdown.write_md(tf, meta.model_dump(mode="json"), post.content)

    # Create runs directory
    config.runs_dir(project_path, name).mkdir(parents=True, exist_ok=True)
    return name


def list_tasks(project_path: Path) -> list[dict]:
    """List all active tasks in a project."""
    td = config.tasks_dir(project_path)
    if not td.exists():
        return []

    tasks = []
    for item in sorted(td.iterdir()):
        if item.name == config.ARCHIVE_DIR or not item.is_dir():
            continue
        tf = item / config.TASK_FILE
        if not tf.exists():
            continue
        meta = markdown.read_frontmatter(tf)
        # Get latest run info
        run_info = _get_latest_run_info(project_path, meta["name"])
        tasks.append({**meta, **run_info})
    return tasks


def count_archived_tasks(project_path: Path) -> int:
    """Count archived (done) tasks."""
    ad = config.archive_dir(project_path)
    if not ad.exists():
        return 0
    return sum(1 for item in ad.iterdir() if item.is_dir())


def show_task(project_path: Path, task_name: str) -> dict:
    """Get full task details including run history."""
    tf = config.task_file(project_path, task_name)
    if not tf.exists():
        raise ValueError(f"Task '{task_name}' not found")

    post = frontmatter.load(str(tf))
    meta = dict(post.metadata)
    meta["body"] = post.content
    meta["project"] = str(project_path)
    meta["branch"] = f"{config.BRANCH_PREFIX}{task_name}"

    # Get all runs
    meta["runs"] = _get_all_runs(project_path, task_name)
    meta.update(_get_latest_run_info(project_path, task_name))
    return meta


def update_task_status(project_path: Path, task_name: str, status: TaskStatus) -> None:
    """Update the status field in task.md."""
    tf = config.task_file(project_path, task_name)
    post = frontmatter.load(str(tf))
    post.metadata["status"] = status.value
    tf.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def merge_task(project_path: Path, task_name: str) -> str:
    """Merge task branch into main and archive. Returns merge commit."""
    tf = config.task_file(project_path, task_name)
    if not tf.exists():
        raise ValueError(f"Task '{task_name}' not found")

    branch = f"{config.BRANCH_PREFIX}{task_name}"
    main_branch = git.get_main_branch(project_path)

    # Checkout main and merge
    git.run_git(["checkout", main_branch], cwd=project_path)
    try:
        commit = git.merge_branch(project_path, branch)
    except git.GitError as e:
        conflict_files = []
        # Abort the failed merge to leave the repo clean
        try:
            conflict_files = git.conflict_files(project_path)
            git.run_git(["merge", "--abort"], cwd=project_path)
        except git.GitError:
            pass
        update_task_status(project_path, task_name, TaskStatus.blocked)
        conflict_summary = ", ".join(conflict_files) if conflict_files else "unknown files"
        init_note = ""
        if any(Path(path).name == "__init__.py" for path in conflict_files):
            init_note = " Note: __init__.py conflicts are often expected when parallel branches update exports/imports."
        raise ValueError(f"Merge conflict: {conflict_summary}.{init_note} {e}") from e

    # Close acpx session before removing worktree
    run_info = _get_latest_run_info(project_path, task_name)
    last_agent = run_info.get("last_agent")
    if last_agent:
        close_session(project_path, task_name, last_agent)

    # Clean up worktree if exists
    worktree_path = project_path / "worktrees" / task_name
    if worktree_path.exists():
        try:
            git.remove_worktree(project_path, worktree_path, branch)
        except git.GitError:
            pass

    # Delete branch
    try:
        git.run_git(["branch", "-D", branch], cwd=project_path)
    except git.GitError:
        pass

    # Archive
    _archive_task(project_path, task_name)
    return commit


def _archive_task(project_path: Path, task_name: str) -> None:
    """Move task to archive directory."""
    src = config.task_dir(project_path, task_name)
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    dest = config.archive_dir(project_path) / f"{date_prefix}-{task_name}"

    # Update status before archiving
    update_task_status(project_path, task_name, TaskStatus.done)
    shutil.move(str(src), str(dest))


def _get_latest_run_info(project_path: Path, task_name: str) -> dict:
    """Get info about the latest run for a task."""
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return {"run_number": 0, "last_purpose": None, "last_agent": None, "last_event": None}

    run_files = sorted(rd.glob("*.md"))
    if not run_files:
        return {"run_number": 0, "last_purpose": None, "last_agent": None, "last_event": None}

    latest = markdown.read_frontmatter(run_files[-1])
    return {
        "run_number": len(run_files),
        "last_purpose": latest.get("purpose"),
        "last_agent": latest.get("agent"),
        "last_status": latest.get("status"),
        "last_event": latest.get("status"),
    }


def _get_all_runs(project_path: Path, task_name: str) -> list[dict]:
    """Get all run records for a task."""
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return []

    runs = []
    for rf in sorted(rd.glob("*.md")):
        post = frontmatter.load(str(rf))
        run_data = dict(post.metadata)
        run_data["body"] = post.content
        runs.append(run_data)
    return runs


def next_run_number(project_path: Path, task_name: str) -> int:
    """Get the next run number for a task."""
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return 1
    return len(list(rd.glob("*.md"))) + 1
