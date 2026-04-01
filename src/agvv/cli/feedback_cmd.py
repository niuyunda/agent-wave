"""feedback subcommand — file issues against the agvv GitHub repo."""

from __future__ import annotations

import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

import typer

from agvv.core import config
from agvv.utils.format import print_error, print_info, print_success

app = typer.Typer(no_args_is_help=True)


@app.command()
def submit(
    title: str = typer.Option(..., "--title", "-t", help="Issue title"),
    body: str = typer.Option("", "--body", "-b", help="Issue body description"),
    issue_type: str = typer.Option("bug", "--type", "-T",
                                    help="Issue type: bug, feature, or refactor"),
) -> None:
    """File an issue against the agvv GitHub repository.

    Wraps ``gh issue create`` so agents can report bugs, feature requests,
    and improvement ideas without leaving the workflow.
    """
    label_map = {
        "bug": "bug",
        "feature": "enhancement",
        "refactor": "refactor",
    }
    label = label_map.get(issue_type, issue_type)

    repo = _resolve_repo()
    if not repo:
        print_error("Could not determine agvv repo. Set gh repo or AGVV_REPO env var.")
        raise typer.Exit(1)

    label_arg = f"--label={label}"
    title_arg = f"--title={title}"
    body_arg = f"--body={body}" if body else ""

    cmd = ["gh", "issue", "create", "--repo", repo, title_arg, label_arg]
    if body_arg:
        cmd.append(body_arg)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            url = result.stdout.strip()
            print_success(f"Issue filed: {url}")
        else:
            print_error(f"gh issue create failed: {result.stderr.strip()}")
            raise typer.Exit(1)
    except FileNotFoundError:
        print_error("`gh` CLI not found. Install GitHub CLI: https://cli.github.com/")
        raise typer.Exit(1)


def _resolve_repo() -> str:
    """Resolve the agvv repo: gh repo view --json owner,name first, then env, then default."""
    # Try gh repo view (active git remote)
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "owner,name", "-q", ".owner.login + \"/\" + .name"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try env override
    repo = Path.cwd() / ".agvv"
    if repo.exists():
        from agvv.core.project import list_projects
        entries = list_projects()
        if entries:
            entry_path = Path(entries[0]["path"])
            agvv_dir = entry_path / ".agvv"
            cfg = agvv_dir / "config.md"
            if cfg.exists():
                for line in cfg.read_text().splitlines():
                    if line.strip().startswith("agvv_repo:"):
                        return line.split(":", 1)[1].strip()

    return config.DEFAULT_AGVV_REPO
