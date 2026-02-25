from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from orch.core import OrchError, adopt_project, cleanup_feature, init_project, parse_kv_pairs, start_feature

app = typer.Typer(help="Orchestrate parallel git worktree workflow for coding tasks.")
project_app = typer.Typer(help="Project-level operations.")
feature_app = typer.Typer(help="Feature branch/worktree operations.")

app.add_typer(project_app, name="project")
app.add_typer(feature_app, name="feature")


def _base_dir(path: str | None) -> Path:
    raw = path or "~/code"
    return Path(raw).expanduser().resolve()


@project_app.command("init")
def project_init(
    project_name: str,
    base_dir: Annotated[str | None, typer.Option("--base-dir", help="Base path containing projects.")] = None,
) -> None:
    """Initialize a new project into bare repo + main worktree layout."""
    try:
        paths = init_project(project_name, _base_dir(base_dir))
    except OrchError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Initialized: {paths.project_dir}")
    typer.echo(f"- bare repo: {paths.repo_dir}")
    typer.echo(f"- main worktree: {paths.main_dir}")
    typer.echo(f"- feature worktrees: {paths.project_dir}/<feature>")


@project_app.command("adopt")
def project_adopt(
    existing_repo: str,
    project_name: str,
    base_dir: Annotated[str | None, typer.Option("--base-dir", help="Base path containing projects.")] = None,
) -> None:
    """Adopt an existing git repository into this layout."""
    try:
        paths, default_branch = adopt_project(Path(existing_repo).expanduser().resolve(), project_name, _base_dir(base_dir))
    except OrchError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Adopted existing repo into worktree layout: {paths.project_dir}")
    typer.echo(f"- source repo: {Path(existing_repo).expanduser().resolve()}")
    typer.echo(f"- bare repo: {paths.repo_dir}")
    typer.echo(f"- main worktree: {paths.main_dir} (branch: {default_branch})")
    typer.echo(f"- feature worktrees: {paths.project_dir}/<feature>")


@feature_app.command("start")
def feature_start(
    project_name: str,
    feature: str,
    base_dir: Annotated[str | None, typer.Option("--base-dir", help="Base path containing projects.")] = None,
    from_branch: Annotated[str, typer.Option("--from-branch", help="Base branch for a new feature branch.")] = "main",
    agent: Annotated[str | None, typer.Option("--agent", help="Agent name/id that requested this feature.")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id", help="Agent task ID or execution ID.")] = None,
    ticket: Annotated[str | None, typer.Option("--ticket", help="Ticket/issue identifier (e.g. JIRA/GitHub).")] = None,
    params: Annotated[list[str], typer.Option("--param", help="Extra context as KEY=VALUE, repeatable.")] = [],
    create_dirs: Annotated[list[str], typer.Option("--mkdir", help="Directories to create in feature worktree.")] = [],
) -> None:
    """Create or reopen a feature worktree and attach agent context metadata."""
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
    except OrchError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Created feature worktree: {paths.feature_dir}")
    typer.echo(f"Branch: {feature}")
    typer.echo(f"Metadata: {paths.feature_dir}/.orch/context.json")


@feature_app.command("cleanup")
def feature_cleanup(
    project_name: str,
    feature: str,
    base_dir: Annotated[str | None, typer.Option("--base-dir", help="Base path containing projects.")] = None,
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
    except OrchError as exc:
        raise typer.BadParameter(str(exc)) from exc

    suffix = " (branch kept)" if keep_branch else ""
    typer.echo(f"Cleaned feature worktree/branch: {feature}{suffix}")


if __name__ == "__main__":
    app()
