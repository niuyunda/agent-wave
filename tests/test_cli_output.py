from __future__ import annotations

import json

from typer.testing import CliRunner

from agvv.cli.main import app
from agvv.core import project
from agvv.utils import git

from tests._support import AgvvRepoTestCase


class CliOutputTest(AgvvRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = CliRunner()

    def test_project_list_defaults_to_json_array(self) -> None:
        result = self.runner.invoke(app, ["projects"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_projects_list_alias(self) -> None:
        result = self.runner.invoke(app, ["projects", "list"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_task_add_auto_registers_project(self) -> None:
        repo = self._create_project_repo("cli-task-add", register=False)
        task_file = self.tmp_path / "cli-task-add.md"
        task_file.write_text(
            "---\nname: cli-task-add\n---\n\n## Goal\nAuto register project.\n",
            encoding="utf-8",
        )

        result = self.runner.invoke(
            app,
            ["tasks", "add", "--project", str(repo), "--file", str(task_file)],
        )

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["project"], str(repo.resolve()))
        self.assertEqual(payload["task"], "cli-task-add")
        self.assertEqual(payload["orchestration"], "auto")
        self.assertFalse(payload["daemon_started"])
        self.assertIsNone(payload["daemon_pid"])
        self.assertEqual([e.path for e in project.list_projects()], [str(repo.resolve())])

        show_result = self.runner.invoke(
            app,
            ["tasks", "show", "cli-task-add", "--project", str(repo)],
        )
        self.assertEqual(show_result.exit_code, 0)
        task_payload = json.loads(show_result.stdout)
        self.assertTrue(task_payload["auto_manage"])
        self.assertEqual(task_payload["feedback_status"], "queued")

    def test_task_add_accepts_agent_option_and_persists_it(self) -> None:
        repo = self._create_project_repo("cli-task-add-agent", register=False)
        task_file = self.tmp_path / "cli-task-add-agent.md"
        task_file.write_text(
            "---\nname: cli-task-add-agent\n---\n\n## Goal\nUse codex.\n",
            encoding="utf-8",
        )

        result = self.runner.invoke(
            app,
            [
                "tasks",
                "add",
                "--project",
                str(repo),
                "--file",
                str(task_file),
                "--agent",
                "codex",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["agent"], "codex")

        show_result = self.runner.invoke(
            app,
            ["tasks", "show", "cli-task-add-agent", "--project", str(repo)],
        )
        self.assertEqual(show_result.exit_code, 0)
        task_payload = json.loads(show_result.stdout)
        self.assertEqual(task_payload["agent"], "codex")
        self.assertIn("with agent 'codex'", task_payload["feedback_message"])

    def test_task_add_rejects_missing_project_dir_without_flag(self) -> None:
        repo = self.tmp_path / "cli-task-add-missing-project"
        task_file = self.tmp_path / "cli-task-add-missing-project.md"
        task_file.write_text(
            "---\nname: cli-task-add-missing-project\n---\n\n## Goal\nDo not auto-create dir.\n",
            encoding="utf-8",
        )

        result = self.runner.invoke(
            app,
            ["tasks", "add", "--project", str(repo), "--file", str(task_file)],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Directory does not exist", result.output)
        self.assertFalse(repo.exists())

    def test_task_add_can_create_missing_project_dir_with_flag(self) -> None:
        repo = self.tmp_path / "cli-task-add-create-project"
        task_file = self.tmp_path / "cli-task-add-create-project.md"
        task_file.write_text(
            "---\nname: cli-task-add-create-project\n---\n\n## Goal\nCreate missing project dir.\n",
            encoding="utf-8",
        )

        env = {
            "GIT_AUTHOR_NAME": "agvv-test",
            "GIT_AUTHOR_EMAIL": "agvv-test@example.com",
            "GIT_COMMITTER_NAME": "agvv-test",
            "GIT_COMMITTER_EMAIL": "agvv-test@example.com",
        }
        result = self.runner.invoke(
            app,
            [
                "tasks",
                "add",
                "--project",
                str(repo),
                "--file",
                str(task_file),
                "--create-project",
            ],
            env=env,
        )

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project"], str(repo.resolve()))
        self.assertTrue(repo.is_dir())
        self.assertTrue(git.is_git_repo(repo))
        self.assertEqual([e.path for e in project.list_projects()], [str(repo.resolve())])

    def test_projects_add_command_removed(self) -> None:
        repo = self.tmp_path / "cli-project-add-removed"
        repo.mkdir()

        result = self.runner.invoke(app, ["projects", "add", str(repo)])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_task_show_defaults_to_json_object(self) -> None:
        repo = self._create_project_repo("cli-task-show")
        self._add_task(repo, "cli-task")

        result = self.runner.invoke(app, ["tasks", "show", "cli-task", "--project", str(repo)])

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "cli-task")
        self.assertEqual(payload["project"], str(repo))
        self.assertEqual(payload["runs"], [])

    def test_task_list_defaults_to_json_array(self) -> None:
        result = self.runner.invoke(app, ["tasks"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_tasks_list_alias(self) -> None:
        result = self.runner.invoke(app, ["tasks", "list"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_runs_sessions_and_checkpoints_commands_removed(self) -> None:
        for args in (["runs"], ["sessions"], ["checkpoints"], ["status"]):
            result = self.runner.invoke(app, args)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("No such command", result.output)

    def test_projects_show_returns_project_task_statuses(self) -> None:
        repo = self._create_project_repo("cli-project-show")
        self._add_task(repo, "show-task")

        result = self.runner.invoke(app, ["projects", "show", str(repo)])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["path"], str(repo.resolve()))
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["tasks"], 1)
        self.assertEqual(payload["task_statuses"][0]["name"], "show-task")

    def test_help_does_not_expose_json_flags(self) -> None:
        commands = [
            ["projects", "--help"],
            ["projects", "list", "--help"],
            ["projects", "show", "--help"],
            ["tasks", "--help"],
            ["tasks", "list", "--help"],
            ["tasks", "show", "--help"],
        ]

        for args in commands:
            result = self.runner.invoke(app, args)
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("--json", result.stdout)

    def test_feedback_command_renamed(self) -> None:
        old_result = self.runner.invoke(app, ["feedbacks", "submit", "--title", "x"])
        new_result = self.runner.invoke(app, ["feedback", "--help"])
        submit_result = self.runner.invoke(app, ["feedback", "submit", "--title", "x"])

        self.assertNotEqual(old_result.exit_code, 0)
        self.assertIn("No such command", old_result.output)
        self.assertEqual(new_result.exit_code, 0)
        self.assertNotIn("submit", new_result.stdout)
        self.assertNotEqual(submit_result.exit_code, 0)
