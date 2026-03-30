"""Checkpoint management logic."""

from __future__ import annotations

from pathlib import Path

from agvv.core import config
from agvv.utils import git, markdown


def show_checkpoint(project_path: Path, task_name: str) -> dict:
    """Show the latest checkpoint info for a task."""
    tf = config.task_file(project_path, task_name)
    if not tf.exists():
        raise ValueError(f"Task '{task_name}' not found")

    # Find the latest run with a checkpoint
    rd = config.runs_dir(project_path, task_name)
    if not rd.exists():
        return {"task": task_name, "checkpoint": None, "message": "No runs yet"}

    run_files = sorted(rd.glob("*.md"))
    latest_meta = markdown.read_frontmatter(run_files[-1]) if run_files else {}
    latest_status = latest_meta.get("status")

    previous_checkpoint = None
    for rf in reversed(run_files):
        meta = markdown.read_frontmatter(rf)
        if meta.get("checkpoint"):
            previous_checkpoint = meta["checkpoint"]
            # Get commit message
            worktree_path = project_path / "worktrees" / task_name
            commit_msg = ""
            cwd = worktree_path if worktree_path.exists() else project_path
            try:
                commit_msg = git.run_git(
                    ["log", "-1", "--format=%B", meta["checkpoint"]], cwd=cwd
                )
            except git.GitError:
                pass

            body = markdown.read_body(rf)
            if rf == run_files[-1]:
                return {
                    "task": task_name,
                    "checkpoint": meta["checkpoint"],
                    "purpose": meta.get("purpose"),
                    "agent": meta.get("agent"),
                    "finished_at": meta.get("finished_at"),
                    "commit_message": commit_msg,
                    "summary": body,
                }

            return {
                "task": task_name,
                "checkpoint": None,
                "message": f"Latest run has no checkpoint (status={latest_status})",
                "latest_run_status": latest_status,
                "previous_checkpoint": meta["checkpoint"],
                "previous_purpose": meta.get("purpose"),
                "previous_agent": meta.get("agent"),
                "previous_finished_at": meta.get("finished_at"),
                "previous_commit_message": commit_msg,
                "previous_summary": body,
            }

    if latest_meta:
        return {
            "task": task_name,
            "checkpoint": None,
            "message": f"Latest run has no checkpoint (status={latest_status})",
            "latest_run_status": latest_status,
            "previous_checkpoint": previous_checkpoint,
        }

    return {"task": task_name, "checkpoint": None, "message": "No checkpoint found"}
