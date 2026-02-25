from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class OrchError(RuntimeError):
    """Raised when an orchestration operation fails."""


@dataclass(frozen=True)
class LayoutPaths:
    project_dir: Path
    repo_dir: Path
    main_dir: Path
    feature_dir: Path | None = None


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise OrchError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        ) from exc


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd)


def _git_success(args: list[str], cwd: Path | None = None) -> bool:
    try:
        _run(["git", *args], cwd=cwd)
        return True
    except OrchError:
        return False


def parse_kv_pairs(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise OrchError(f"Invalid --param value '{pair}'. Expected KEY=VALUE.")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise OrchError(f"Invalid --param value '{pair}'. Key cannot be empty.")
        result[key] = value
    return result


def layout_paths(project_name: str, base_dir: Path, feature: str | None = None) -> LayoutPaths:
    project_dir = base_dir / project_name
    return LayoutPaths(
        project_dir=project_dir,
        repo_dir=project_dir / "repo.git",
        main_dir=project_dir / "main",
        feature_dir=(project_dir / feature) if feature else None,
    )


def _ensure_feature_name(feature: str) -> None:
    if feature in {"main", "repo.git"}:
        raise OrchError(f"Feature branch name '{feature}' is reserved in this layout.")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_branch(repo_dir: Path) -> str:
    branches_raw = _git(["-C", str(repo_dir), "for-each-ref", "--format=%(refname:short)", "refs/heads"]).stdout
    branches = [line.strip() for line in branches_raw.splitlines() if line.strip()]
    if not branches:
        raise OrchError("No branches found in bare repo.")
    for preferred in ("main", "master"):
        if preferred in branches:
            return preferred
    return branches[0]


def init_project(project_name: str, base_dir: Path) -> LayoutPaths:
    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if not paths.repo_dir.exists():
        _git(["init", "--bare", str(paths.repo_dir)])

    if not paths.main_dir.exists():
        if _git_success(["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", "refs/heads/main"]):
            _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), "main"])
        else:
            _git(["-C", str(paths.repo_dir), "worktree", "add", "-b", "main", str(paths.main_dir)])

    if not _git_success(["-C", str(paths.main_dir), "rev-parse", "--verify", "HEAD"]):
        _git(["-C", str(paths.main_dir), "commit", "--allow-empty", "-m", "init: bare repo setup"])

    return paths


def adopt_project(existing_repo: Path, project_name: str, base_dir: Path) -> tuple[LayoutPaths, str]:
    if not (existing_repo / ".git").exists():
        raise OrchError(f"{existing_repo} is not a git repository.")

    paths = layout_paths(project_name, base_dir)
    paths.project_dir.mkdir(parents=True, exist_ok=True)

    if paths.repo_dir.exists() or paths.main_dir.exists():
        raise OrchError(
            f"Target project already initialized at {paths.project_dir}. "
            "Use a different project name or clean target first."
        )

    _git(["clone", "--mirror", str(existing_repo), str(paths.repo_dir)])
    branch = _default_branch(paths.repo_dir)
    _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.main_dir), branch])
    return paths, branch


def start_feature(
    project_name: str,
    feature: str,
    base_dir: Path,
    from_branch: str,
    agent: str | None,
    task_id: str | None,
    ticket: str | None,
    params: dict[str, str],
    create_dirs: list[str],
) -> LayoutPaths:
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    assert paths.feature_dir is not None

    if not paths.repo_dir.exists() or not paths.main_dir.exists():
        raise OrchError(
            f"Project not initialized at {paths.project_dir}. "
            "Run `orch project init` or `orch project adopt` first."
        )

    if paths.feature_dir.exists():
        raise OrchError(f"Feature worktree path already exists: {paths.feature_dir}")

    branch_exists = _git_success(
        ["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]
    )
    if branch_exists:
        _git(["-C", str(paths.repo_dir), "worktree", "add", str(paths.feature_dir), feature])
    else:
        _git(["-C", str(paths.repo_dir), "worktree", "add", "-b", feature, str(paths.feature_dir), from_branch])

    for directory in create_dirs:
        (paths.feature_dir / directory).mkdir(parents=True, exist_ok=True)

    metadata = {
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "project_name": project_name,
        "feature": feature,
        "base_dir": str(base_dir),
        "from_branch": from_branch,
        "agent": agent,
        "task_id": task_id,
        "ticket": ticket,
        "params": params,
        "created_dirs": create_dirs,
    }
    _write_json(paths.feature_dir / ".orch" / "context.json", metadata)
    return paths


def cleanup_feature(
    project_name: str,
    feature: str,
    base_dir: Path,
    delete_branch: bool,
) -> LayoutPaths:
    _ensure_feature_name(feature)
    paths = layout_paths(project_name, base_dir, feature=feature)
    assert paths.feature_dir is not None

    if not paths.repo_dir.exists():
        raise OrchError(f"Repo not found: {paths.repo_dir}")

    if paths.feature_dir.exists():
        _git(["-C", str(paths.repo_dir), "worktree", "remove", str(paths.feature_dir), "--force"])

    if delete_branch and _git_success(
        ["-C", str(paths.repo_dir), "show-ref", "--verify", "--quiet", f"refs/heads/{feature}"]
    ):
        _git(["-C", str(paths.repo_dir), "branch", "-D", feature])

    return paths
