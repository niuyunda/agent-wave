"""feedback command - save local feedback, optionally file GitHub issues."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import typer

from agvv.core import config
from agvv.utils.format import print_error, print_success

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@app.callback()
def feedback(
    title: str = typer.Option(..., "--title", "-t", help="Issue title"),
    body: str = typer.Option("", "--body", "-b", help="Issue body description"),
    issue_type: str = typer.Option("bug", "--type", "-T",
                                    help="Issue type: bug, feature, or refactor"),
    issue: bool = typer.Option(
        False,
        "--issue",
        help="Also file a GitHub issue (default: save local feedback only).",
    ),
) -> None:
    """Record feedback under ``~/.agvv/feedback.json`` and optionally file an issue."""
    config.ensure_agvv_home()
    issue_url: str | None = None
    issue_error: str | None = None
    repo: str | None = None

    if issue:
        repo = _resolve_repo()
        try:
            issue_url = _create_issue(title=title, body=body, issue_type=issue_type, repo=repo)
        except RuntimeError as exc:
            issue_error = str(exc)

    entry = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "body": body,
        "type": issue_type,
        "issue_requested": issue,
    }
    if repo:
        entry["issue_repo"] = repo
    if issue_url:
        entry["issue_url"] = issue_url
    if issue_error:
        entry["issue_error"] = issue_error

    try:
        feedback_path = _append_feedback(entry)
    except OSError as exc:
        print_error(f"Failed to save feedback locally: {exc}")
        raise typer.Exit(1)

    if issue_error:
        print_error(f"Feedback saved to {feedback_path}; issue filing failed: {issue_error}")
        raise typer.Exit(1)
    if issue_url:
        print_success("Feedback saved and issue filed", path=str(feedback_path), issue=issue_url)
        return
    print_success("Feedback saved", path=str(feedback_path))


def _create_issue(title: str, body: str, issue_type: str, repo: str) -> str:
    label_map = {
        "bug": "bug",
        "feature": "enhancement",
        "refactor": "refactor",
    }
    label = label_map.get(issue_type, issue_type)
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--label",
        label,
    ]
    if body:
        cmd.extend(["--body", body])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("`gh` CLI not found. Install GitHub CLI: https://cli.github.com/")
    if result.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _append_feedback(entry: dict) -> Path:
    path = config.feedback_path()
    entries = _read_feedback_entries(path)
    entries.append(entry)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _read_feedback_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    entries: list[dict] = []
    for item in payload:
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _resolve_repo() -> str:
    """Resolve target issue repo for agvv feedback."""
    from_env = os.environ.get("AGVV_REPO", "").strip()
    if from_env:
        return _normalize_repo_ref(from_env)
    return config.DEFAULT_AGVV_REPO


def _normalize_repo_ref(repo: str) -> str:
    candidate = repo.strip()
    if candidate.startswith(("https://github.com/", "http://github.com/")):
        tail = candidate.rstrip("/").split("github.com/", 1)[1]
        parts = [p for p in tail.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return candidate
