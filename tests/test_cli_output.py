from __future__ import annotations

import json

from typer.testing import CliRunner

from agvv.cli.main import app
from agvv.core import project

from tests._support import AgvvRepoTestCase


class CliOutputTest(AgvvRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = CliRunner()

    def test_project_list_defaults_to_json_array(self) -> None:
        result = self.runner.invoke(app, ["projects"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_projects_list_subcommand_removed(self) -> None:
        result = self.runner.invoke(app, ["projects", "list"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

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

    def test_tasks_list_subcommand_removed(self) -> None:
        result = self.runner.invoke(app, ["tasks", "list"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_run_status_defaults_to_json_array(self) -> None:
        repo = self._create_project_repo("cli-run-status")
        self._add_task(repo, "idle-task")

        result = self.runner.invoke(app, ["runs", "status", "--project", str(repo)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_session_status_returns_structured_payload(self) -> None:
        repo = self._create_project_repo("cli-session-status")
        self._add_task(repo, "sessionless-task")

        result = self.runner.invoke(
            app,
            ["sessions", "status", "sessionless-task", "--agent", "codex", "--project", str(repo)],
        )

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task"], "sessionless-task")
        self.assertEqual(payload["agent"], "codex")
        self.assertIn("active", payload)

    def test_help_does_not_expose_json_flags(self) -> None:
        commands = [
            ["projects", "--help"],
            ["tasks", "--help"],
            ["tasks", "show", "--help"],
            ["runs", "status", "--help"],
            ["sessions", "status", "--help"],
            ["sessions", "list", "--help"],
            ["checkpoints", "show", "--help"],
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
