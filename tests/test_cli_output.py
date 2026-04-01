from __future__ import annotations

import json

from typer.testing import CliRunner

from agvv.cli.main import app

from tests._support import AgvvRepoTestCase


class CliOutputTest(AgvvRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = CliRunner()

    def test_project_list_defaults_to_json_array(self) -> None:
        result = self.runner.invoke(app, ["project", "list"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_project_add_returns_json_object(self) -> None:
        repo = self.tmp_path / "cli-project-add"
        repo.mkdir()

        result = self.runner.invoke(app, ["project", "add", str(repo)])

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path"], str(repo.resolve()))

    def test_task_show_defaults_to_json_object(self) -> None:
        repo = self._create_project_repo("cli-task-show")
        self._add_task(repo, "cli-task")

        result = self.runner.invoke(app, ["task", "show", "cli-task", "--project", str(repo)])

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "cli-task")
        self.assertEqual(payload["project"], str(repo))
        self.assertEqual(payload["runs"], [])

    def test_run_status_defaults_to_json_array(self) -> None:
        repo = self._create_project_repo("cli-run-status")
        self._add_task(repo, "idle-task")

        result = self.runner.invoke(app, ["run", "status", "--project", str(repo)])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_session_status_returns_structured_payload(self) -> None:
        repo = self._create_project_repo("cli-session-status")
        self._add_task(repo, "sessionless-task")

        result = self.runner.invoke(
            app,
            ["session", "status", "sessionless-task", "--agent", "codex", "--project", str(repo)],
        )

        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task"], "sessionless-task")
        self.assertEqual(payload["agent"], "codex")
        self.assertIn("active", payload)

    def test_help_does_not_expose_json_flags(self) -> None:
        commands = [
            ["project", "list", "--help"],
            ["task", "list", "--help"],
            ["task", "show", "--help"],
            ["run", "status", "--help"],
            ["session", "status", "--help"],
            ["session", "list", "--help"],
            ["checkpoint", "show", "--help"],
        ]

        for args in commands:
            result = self.runner.invoke(app, args)
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("--json", result.stdout)
