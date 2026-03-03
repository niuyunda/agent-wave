from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agvv.orchestration import AgvvError, adopt_project, cleanup_feature, commit_and_push_branch, init_project, start_feature


def _git(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *cmd], cwd=cwd, text=True, capture_output=True, check=True)


def _create_existing_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", branch], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test User"], cwd=path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "init repo"], cwd=path)
    return path


def _create_existing_repo_with_remote(path: Path, remote_bare: Path, branch: str = "main") -> Path:
    repo = _create_existing_repo(path, branch=branch)
    _git(["remote", "add", "origin", str(remote_bare)], cwd=repo)
    _git(["push", "-u", "origin", branch], cwd=repo)
    return repo


def test_init_project_creates_layout_and_is_idempotent(tmp_path: Path) -> None:
    paths = init_project("demo", tmp_path)
    assert paths.repo_dir.exists()
    assert paths.main_dir.exists()
    assert (paths.repo_dir / "HEAD").exists()
    second = init_project("demo", tmp_path)
    assert second.project_dir == paths.project_dir
    assert second.main_dir.exists()


def test_init_project_attaches_existing_main_branch_to_missing_main_worktree(tmp_path: Path) -> None:
    paths = init_project("demo", tmp_path / "base")
    _git(["-C", str(paths.repo_dir), "worktree", "remove", str(paths.main_dir), "--force"], cwd=tmp_path)
    assert not paths.main_dir.exists()
    restored = init_project("demo", tmp_path / "base")
    assert restored.main_dir.exists()


def test_adopt_project_success_with_default_branch_preference(tmp_path: Path) -> None:
    existing_repo = _create_existing_repo(tmp_path / "src", branch="develop")
    paths, branch = adopt_project(existing_repo, "adopted", tmp_path)
    assert branch == "develop"
    assert paths.repo_dir.exists()
    assert paths.main_dir.exists()


def test_adopt_project_prefers_main_when_present(tmp_path: Path) -> None:
    existing_repo = _create_existing_repo(tmp_path / "src-main", branch="main")
    paths, branch = adopt_project(existing_repo, "adopted-main", tmp_path)
    assert branch == "main"
    assert paths.main_dir.exists()


def test_adopt_project_allows_branch_push_after_start_feature(tmp_path: Path) -> None:
    remote_bare = tmp_path / "upstream.git"
    _git(["init", "--bare", str(remote_bare)], cwd=tmp_path)
    existing_repo = _create_existing_repo_with_remote(tmp_path / "src-upstream", remote_bare, branch="main")

    adopt_project(existing_repo, "adopted-push", tmp_path)
    paths = start_feature(
        project_name="adopted-push",
        feature="feat-push",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    assert paths.feature_dir is not None
    (paths.feature_dir / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    commit_and_push_branch(
        worktree=paths.feature_dir,
        feature="feat-push",
        base_branch="main",
        remote="origin",
        commit_message="feat: add calculator helper",
    )

    pushed = subprocess.run(
        ["git", "-C", str(remote_bare), "show-ref", "--verify", "--quiet", "refs/heads/feat-push"],
        check=False,
    )
    assert pushed.returncode == 0


def test_adopt_project_fails_when_source_not_git_repo(tmp_path: Path) -> None:
    src = tmp_path / "not-a-repo"
    src.mkdir()
    with pytest.raises(AgvvError):
        adopt_project(src, "adopted", tmp_path)


def test_adopt_project_fails_when_target_already_initialized(tmp_path: Path) -> None:
    existing_repo = _create_existing_repo(tmp_path / "src-main")
    target = tmp_path / "adopted"
    target.mkdir()
    (target / "repo.git").mkdir()
    with pytest.raises(AgvvError):
        adopt_project(existing_repo, "adopted", tmp_path)


def test_adopt_project_fails_when_bare_repo_has_no_branches(tmp_path: Path) -> None:
    src = tmp_path / "src-empty"
    src.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=src)
    with pytest.raises(AgvvError, match="No branches found in bare repo"):
        adopt_project(src, "adopted-empty", tmp_path)


def test_start_feature_creates_worktree_metadata_and_dirs(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    paths = start_feature(
        project_name="demo",
        feature="feat-1",
        base_dir=tmp_path,
        from_branch="main",
        agent="codex",
        task_id="task-1",
        ticket="PROJ-1",
        params={"lang": "python"},
        create_dirs=["src", "tests/unit"],
    )
    assert paths.feature_dir is not None
    assert paths.feature_dir.exists()
    assert (paths.feature_dir / "src").exists()
    assert (paths.feature_dir / "tests" / "unit").exists()
    metadata = json.loads((paths.feature_dir / ".agvv" / "context.json").read_text(encoding="utf-8"))
    assert metadata["agent"] == "codex"
    assert metadata["task_id"] == "task-1"
    assert metadata["ticket"] == "PROJ-1"
    assert metadata["params"] == {"lang": "python"}


def test_start_feature_fails_on_reserved_name(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    with pytest.raises(AgvvError):
        start_feature(
            project_name="demo",
            feature="main",
            base_dir=tmp_path,
            from_branch="main",
            agent=None,
            task_id=None,
            ticket=None,
            params={},
            create_dirs=[],
        )


def test_start_feature_fails_when_project_not_initialized(tmp_path: Path) -> None:
    with pytest.raises(AgvvError):
        start_feature(
            project_name="missing",
            feature="feat-1",
            base_dir=tmp_path,
            from_branch="main",
            agent=None,
            task_id=None,
            ticket=None,
            params={},
            create_dirs=[],
        )


def test_start_feature_reuses_existing_branch_after_cleanup_keep_branch(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    first = start_feature(
        project_name="demo",
        feature="feat-reuse",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    assert first.feature_dir is not None and first.feature_dir.exists()
    cleanup_feature("demo", "feat-reuse", tmp_path, delete_branch=False)
    second = start_feature(
        project_name="demo",
        feature="feat-reuse",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    assert second.feature_dir is not None and second.feature_dir.exists()


def test_start_feature_fails_when_feature_worktree_path_exists(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    (tmp_path / "demo" / "feat-exists").mkdir(parents=True, exist_ok=True)
    with pytest.raises(AgvvError):
        start_feature(
            project_name="demo",
            feature="feat-exists",
            base_dir=tmp_path,
            from_branch="main",
            agent=None,
            task_id=None,
            ticket=None,
            params={},
            create_dirs=[],
        )


def test_cleanup_feature_deletes_branch_by_default(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    start_feature(
        project_name="demo",
        feature="feat-clean",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    paths = cleanup_feature("demo", "feat-clean", tmp_path, delete_branch=True)
    assert paths.feature_dir is not None
    assert not paths.feature_dir.exists()
    repo = tmp_path / "demo" / "repo.git"
    branch_check = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/heads/feat-clean"],
        check=False,
    )
    assert branch_check.returncode != 0


def test_cleanup_feature_deletes_branch_when_worktree_already_missing(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    paths = start_feature(
        project_name="demo",
        feature="feat-missing-wt",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    assert paths.feature_dir is not None
    repo = tmp_path / "demo" / "repo.git"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(paths.feature_dir), "--force"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not paths.feature_dir.exists()
    cleanup_feature("demo", "feat-missing-wt", tmp_path, delete_branch=True)
    branch_check = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/heads/feat-missing-wt"],
        check=False,
    )
    assert branch_check.returncode != 0


def test_cleanup_feature_fails_when_repo_missing(tmp_path: Path) -> None:
    with pytest.raises(AgvvError):
        cleanup_feature("demo", "feat-any", tmp_path, delete_branch=True)


def test_cleanup_feature_fails_when_untracked_files_exist(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    paths = start_feature(
        project_name="demo",
        feature="feat-dirty",
        base_dir=tmp_path,
        from_branch="main",
        agent=None,
        task_id=None,
        ticket=None,
        params={},
        create_dirs=[],
    )
    assert paths.feature_dir is not None
    (paths.feature_dir / "scratch.txt").write_text("draft\n", encoding="utf-8")
    with pytest.raises(AgvvError, match="uncommitted changes"):
        cleanup_feature("demo", "feat-dirty", tmp_path, delete_branch=True)


def test_cleanup_feature_fails_on_reserved_name(tmp_path: Path) -> None:
    with pytest.raises(AgvvError):
        cleanup_feature("demo", "repo.git", tmp_path, delete_branch=True)
