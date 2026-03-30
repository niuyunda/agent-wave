from __future__ import annotations

from pathlib import Path

from agvv.core import config, project

from tests._support import AgvvRepoTestCase


class ProjectTest(AgvvRepoTestCase):
    def test_add_project_initializes_registry_and_default_files(self) -> None:
        repo = self.tmp_path / "project-init"
        repo.mkdir()

        entry = project.add_project(repo)

        self.assertEqual(Path(entry.path), repo.resolve())
        self.assertEqual([e.path for e in project.list_projects()], [str(repo.resolve())])
        self.assertTrue((repo / ".agvv" / config.CONFIG_FILE).exists())
        self.assertTrue(config.tasks_dir(repo).is_dir())
        self.assertTrue(config.archive_dir(repo).is_dir())

    def test_add_project_rejects_missing_directory_and_duplicates(self) -> None:
        missing = self.tmp_path / "missing-project"
        with self.assertRaisesRegex(ValueError, "Directory does not exist"):
            project.add_project(missing)

        repo = self._create_project_repo("duplicate-project", register=False)
        project.add_project(repo)
        with self.assertRaisesRegex(ValueError, "already registered"):
            project.add_project(repo)

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
