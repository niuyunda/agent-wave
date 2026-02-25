from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orch.core import OrchError, adopt_project, cleanup_feature, init_project, parse_kv_pairs, start_feature


def _git(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *cmd], cwd=cwd, text=True, capture_output=True, check=True)


def _create_existing_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", branch], cwd=path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "init repo"], cwd=path)
    return path


def test_parse_kv_pairs_success() -> None:
    assert parse_kv_pairs(["a=1", "b=two=parts"]) == {"a": "1", "b": "two=parts"}


@pytest.mark.parametrize("value", ["invalid", "=missing_key"])
def test_parse_kv_pairs_invalid(value: str) -> None:
    with pytest.raises(OrchError):
        parse_kv_pairs([value])


def test_init_project_creates_layout_and_is_idempotent(tmp_path: Path) -> None:
    paths = init_project("demo", tmp_path)
    assert paths.repo_dir.exists()
    assert paths.main_dir.exists()
    assert (paths.repo_dir / "HEAD").exists()

    # Re-run should not fail and should keep same layout.
    second = init_project("demo", tmp_path)
    assert second.project_dir == paths.project_dir
    assert second.main_dir.exists()


def test_init_project_attaches_existing_main_branch_to_missing_main_worktree(tmp_path: Path) -> None:
    base = tmp_path / "base"
    project = "demo"
    paths = init_project(project, base)

    _git(["-C", str(paths.repo_dir), "worktree", "remove", str(paths.main_dir), "--force"], cwd=tmp_path)
    assert not paths.main_dir.exists()

    restored = init_project(project, base)
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


def test_adopt_project_fails_when_source_not_git_repo(tmp_path: Path) -> None:
    src = tmp_path / "not-a-repo"
    src.mkdir()
    with pytest.raises(OrchError):
        adopt_project(src, "adopted", tmp_path)


def test_adopt_project_fails_when_target_already_initialized(tmp_path: Path) -> None:
    existing_repo = _create_existing_repo(tmp_path / "src-main")
    target = tmp_path / "adopted"
    target.mkdir()
    (target / "repo.git").mkdir()
    with pytest.raises(OrchError):
        adopt_project(existing_repo, "adopted", tmp_path)


def test_adopt_project_fails_when_bare_repo_has_no_branches(tmp_path: Path) -> None:
    src = tmp_path / "src-empty"
    src.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=src)

    with pytest.raises(OrchError, match="No branches found in bare repo"):
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

    metadata_path = paths.feature_dir / ".orch" / "context.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["agent"] == "codex"
    assert metadata["task_id"] == "task-1"
    assert metadata["ticket"] == "PROJ-1"
    assert metadata["params"] == {"lang": "python"}


def test_start_feature_fails_on_reserved_name(tmp_path: Path) -> None:
    init_project("demo", tmp_path)
    with pytest.raises(OrchError):
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
    with pytest.raises(OrchError):
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
    project_dir = tmp_path / "demo"
    (project_dir / "feat-exists").mkdir(parents=True, exist_ok=True)

    with pytest.raises(OrchError):
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
    with pytest.raises(OrchError):
        cleanup_feature("demo", "feat-any", tmp_path, delete_branch=True)


def test_cleanup_feature_fails_on_reserved_name(tmp_path: Path) -> None:
    with pytest.raises(OrchError):
        cleanup_feature("demo", "repo.git", tmp_path, delete_branch=True)
