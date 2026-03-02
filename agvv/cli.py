"""Typer command-line interface for Agent Wave workflows."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from agvv.core import (
    AgvvError,
    adopt_project,
    check_pr_status,
    cleanup_feature,
    create_orch_task,
    init_project,
    list_tasks,
    parse_kv_pairs,
    start_feature,
)

app = typer.Typer(help="Agent Wave: orchestrate parallel git worktree workflow for coding tasks.")
project_app = typer.Typer(help="Project-level operations.")
feature_app = typer.Typer(help="Feature branch/worktree operations.")
orch_app = typer.Typer(help="Task orchestration registry operations.")
pr_app = typer.Typer(help="Pull request review-loop operations.")
_DEFAULT_BASE_DIR = "~/code"
_LOGGER = logging.getLogger(__name__)

app.add_typer(project_app, name="project")
app.add_typer(feature_app, name="feature")
app.add_typer(orch_app, name="orch")
app.add_typer(pr_app, name="pr")


def _base_dir(path: str | None) -> Path:
    """Resolve the base directory, defaulting to ``~/code``."""

    raw = path
    if raw is None:
        raw = _DEFAULT_BASE_DIR
        _LOGGER.warning("No --base-dir provided; using default base directory: %s", raw)
    return Path(raw).expanduser().resolve()


def _exit_with_agvv_error(exc: AgvvError) -> None:
    """Render operational errors to stderr and exit non-zero."""

    typer.secho(str(exc), err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1) from exc


def _resolve_optional_path(path: str | None) -> Path | None:
    """Resolve an optional path string to an absolute ``Path``."""

    return Path(path).expanduser().resolve() if path else None


@project_app.command("init")
def project_init(
    project_name: str,
    base_dir: Annotated[
        str | None, typer.Option("--base-dir", help=f"Base path containing projects. Default: {_DEFAULT_BASE_DIR}")
    ] = None,
) -> None:
    """Initialize a new project into bare repo + main worktree layout."""
    try:
        paths = init_project(project_name, _base_dir(base_dir))
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(f"Initialized: {paths.project_dir}")
    typer.echo(f"- bare repo: {paths.repo_dir}")
    typer.echo(f"- main worktree: {paths.main_dir}")
    typer.echo(f"- feature worktrees: {paths.project_dir}/<feature>")


@project_app.command("adopt")
def project_adopt(
    existing_repo: str,
    project_name: str,
    base_dir: Annotated[
        str | None, typer.Option("--base-dir", help=f"Base path containing projects. Default: {_DEFAULT_BASE_DIR}")
    ] = None,
) -> None:
    """Adopt an existing git repository into this layout."""
    repo_path = Path(existing_repo).expanduser().resolve()
    try:
        paths, default_branch = adopt_project(repo_path, project_name, _base_dir(base_dir))
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(f"Adopted existing repo into worktree layout: {paths.project_dir}")
    typer.echo(f"- source repo: {repo_path}")
    typer.echo(f"- bare repo: {paths.repo_dir}")
    typer.echo(f"- main worktree: {paths.main_dir} (branch: {default_branch})")
    typer.echo(f"- feature worktrees: {paths.project_dir}/<feature>")


@feature_app.command("start")
def feature_start(
    project_name: str,
    feature: str,
    base_dir: Annotated[
        str | None, typer.Option("--base-dir", help=f"Base path containing projects. Default: {_DEFAULT_BASE_DIR}")
    ] = None,
    from_branch: Annotated[str, typer.Option("--from-branch", help="Base branch for a new feature branch.")] = "main",
    agent: Annotated[str | None, typer.Option("--agent", help="Agent name/id that requested this feature.")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help="Agent task ID or execution ID.")] = None,
    ticket: Annotated[str | None, typer.Option("--ticket", help="Ticket/issue identifier (e.g. JIRA/GitHub).")] = None,
    params: Annotated[list[str] | None, typer.Option("--param", help="Extra context as KEY=VALUE, repeatable.")] = None,
    create_dirs: Annotated[
        list[str] | None, typer.Option("--mkdir", help="Directories to create in feature worktree.")
    ] = None,
) -> None:
    """Create or reopen a feature worktree and attach agent context metadata."""
    params = params or []
    create_dirs = create_dirs or []
    try:
        paths = start_feature(
            project_name=project_name,
            feature=feature,
            base_dir=_base_dir(base_dir),
            from_branch=from_branch,
            agent=agent,
            task_id=task_id,
            ticket=ticket,
            params=parse_kv_pairs(params),
            create_dirs=create_dirs,
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(f"Created feature worktree: {paths.feature_dir}")
    typer.echo(f"Branch: {feature}")
    typer.echo(f"Metadata: {paths.feature_dir}/.agvv/context.json")


@feature_app.command("cleanup")
def feature_cleanup(
    project_name: str,
    feature: str,
    base_dir: Annotated[
        str | None, typer.Option("--base-dir", help=f"Base path containing projects. Default: {_DEFAULT_BASE_DIR}")
    ] = None,
    keep_branch: Annotated[bool, typer.Option("--keep-branch", help="Keep branch and only remove worktree.")] = False,
) -> None:
    """Cleanup merged feature worktree and optionally delete branch."""
    try:
        cleanup_feature(
            project_name=project_name,
            feature=feature,
            base_dir=_base_dir(base_dir),
            delete_branch=not keep_branch,
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    suffix = " (branch kept)" if keep_branch else ""
    typer.echo(f"Cleaned feature worktree/branch: {feature}{suffix}")


@orch_app.command("spawn")
def orch_spawn(
    project_name: str,
    feature: str,
    task_id: Annotated[str, typer.Option("--task-id", help="Unique task id.")],
    session: Annotated[str, typer.Option("--session", help="tmux session name.")],
    agent_cmd: Annotated[str, typer.Option("--agent-cmd", help="Agent command to run inside tmux session.")],
    agent: Annotated[str, typer.Option("--agent", help="Agent name (e.g. codex).")],
    base_dir: Annotated[
        str | None, typer.Option("--base-dir", help=f"Base path containing projects. Default: {_DEFAULT_BASE_DIR}")
    ] = None,
    from_branch: Annotated[str, typer.Option("--from-branch", help="Base branch for new feature worktree.")] = "main",
    tasks_path: Annotated[
        str | None,
        typer.Option(
            "--tasks-path",
            help="Path to tasks registry JSON (default: AGVV_TASKS_PATH or ~/.agvv/tasks.json).",
        ),
    ] = None,
) -> None:
    """Create a running orchestration task (worktree + tmux + registry)."""

    try:
        task = create_orch_task(
            project_name=project_name,
            feature=feature,
            base_dir=_base_dir(base_dir),
            task_id=task_id,
            session=session,
            agent=agent,
            agent_cmd=agent_cmd,
            from_branch=from_branch,
            tasks_path=_resolve_optional_path(tasks_path),
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(
        f"Spawned task: {task.id} status={task.status} "
        f"target={task.project_name}/{task.feature} session={task.session}"
    )


@orch_app.command("list")
def orch_list(
    tasks_path: Annotated[
        str | None,
        typer.Option(
            "--tasks-path",
            help="Path to tasks registry JSON (default: AGVV_TASKS_PATH or ~/.agvv/tasks.json).",
        ),
    ] = None,
    project_name: Annotated[str | None, typer.Option("--project", help="Filter by project name.")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by task status.")] = None,
) -> None:
    """List orchestration tasks from the registry."""

    try:
        task_items = list_tasks(
            path=_resolve_optional_path(tasks_path),
            project_name=project_name,
            status=status,
        )
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    if not task_items:
        typer.echo("No tasks found.")
        return

    for task in task_items:
        session = task.session or "-"
        agent = task.agent or "-"
        typer.echo(
            f"{task.id}\t{task.status}\t{task.project_name}/{task.feature}\t"
            f"session={session}\tagent={agent}\tupdated={task.updated_at}"
        )


@pr_app.command("check")
def pr_check(
    repo: Annotated[str, typer.Option("--repo", help="GitHub repo in owner/name format.")],
    pr_number: Annotated[int, typer.Option("--pr", help="PR number to check.")],
) -> None:
    """Check PR result for short review loop (<=1 hour)."""

    try:
        result = check_pr_status(repo=repo, pr_number=pr_number)
    except AgvvError as exc:
        _exit_with_agvv_error(exc)

    typer.echo(
        f"status={result.status}\treason={result.reason}\tstate={result.state}\t"
        f"review={result.review_decision or '-'}"
    )


if __name__ == "__main__":
    app()
