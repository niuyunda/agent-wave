from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agvv.core import config, project
from agvv.utils import git

from tests._support import AgvvRepoTestCase


class ProjectTest(AgvvRepoTestCase):
    def test_ensure_project_is_idempotent(self) -> None:
        repo = self._create_project_repo("ensure-project", register=False)

        first = project.ensure_project(repo)
        second = project.ensure_project(repo)

        self.assertEqual(Path(first.path), repo.resolve())
        self.assertEqual(Path(second.path), repo.resolve())
        self.assertEqual([e.path for e in project.list_projects()], [str(repo.resolve())])
        self.assertTrue((repo / ".agvv" / config.CONFIG_FILE).exists())

    def test_add_project_initializes_registry_and_default_files(self) -> None:
        repo = self.tmp_path / "project-init"
        repo.mkdir()

        entry = project.add_project(repo)

        self.assertEqual(Path(entry.path), repo.resolve())
        self.assertEqual([e.path for e in project.list_projects()], [str(repo.resolve())])
        self.assertTrue((repo / ".agvv" / config.CONFIG_FILE).exists())
        for hook_name in ("after_create", "before_run", "after_run"):
            self.assertTrue((repo / ".agvv" / config.HOOKS_DIR / f"{hook_name}.sh").exists())
        self.assertTrue(config.tasks_dir(repo).is_dir())
        self.assertTrue(config.archive_dir(repo).is_dir())

        raw_cfg = json.loads((repo / ".agvv" / config.CONFIG_FILE).read_text(encoding="utf-8"))
        self.assertEqual(raw_cfg.get("agvv_repo"), "https://github.com/niuyunda/agent-wave")
        self.assertEqual(
            set(raw_cfg.get("hooks", {}).keys()),
            {"after_create", "before_run", "after_run"},
        )

    def test_add_project_rejects_missing_directory_and_duplicates(self) -> None:
        missing = self.tmp_path / "missing-project"
        with self.assertRaisesRegex(ValueError, "Directory does not exist"):
            project.add_project(missing)

        repo = self._create_project_repo("duplicate-project", register=False)
        project.add_project(repo)
        with self.assertRaisesRegex(ValueError, "already registered"):
            project.add_project(repo)

    def test_add_project_initializes_git_repo_when_missing(self) -> None:
        repo = self.tmp_path / "plain-project"
        repo.mkdir()
        (repo / "README.md").write_text("# plain\n", encoding="utf-8")

        entry = project.add_project(repo)

        self.assertEqual(Path(entry.path), repo.resolve())
        self.assertTrue(git.is_git_repo(repo))
        self.assertTrue(git.has_commits(repo))
        tracked = git.run_git(["ls-files"], cwd=repo).splitlines()
        self.assertIn("README.md", tracked)

    def test_add_project_bootstraps_existing_repo_without_commits(self) -> None:
        repo = self.tmp_path / "repo-no-head"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "agvv-test"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "agvv-test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
        (repo / "README.md").write_text("# no-head\n", encoding="utf-8")

        project.add_project(repo)

        self.assertTrue(git.has_commits(repo))
        tracked = git.run_git(["ls-files"], cwd=repo).splitlines()
        self.assertIn("README.md", tracked)

    def test_find_and_resolve_project_from_task_name(self) -> None:
        repo_a = self._create_project_repo("lookup-a")
        repo_b = self._create_project_repo("lookup-b")
        self._add_task(repo_b, "lookup-task")

        self.assertEqual(project.find_project_for_task("lookup-task"), repo_b)
        self.assertEqual(project.resolve_project(None, "lookup-task"), repo_b)
        self.assertEqual(project.resolve_project(str(repo_a)), repo_a)

    def test_remove_project_unregisters_but_keeps_project_files(self) -> None:
        repo = self._create_project_repo("remove-project")

        project.remove_project(repo)

        self.assertEqual(project.list_projects(), [])
        self.assertTrue((repo / ".agvv").exists())
        with self.assertRaisesRegex(ValueError, "Project not registered"):
            project.remove_project(repo)

    def test_resolve_project_requires_explicit_project_or_task_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "--project is required"):
            project.resolve_project(None)
