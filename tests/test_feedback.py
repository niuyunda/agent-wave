from __future__ import annotations

import json
import os
from unittest import mock

from typer.testing import CliRunner

from agvv.cli.main import app
from agvv.cli import feedback_cmd
from agvv.core import config
from tests._support import AgvvRepoTestCase


class FeedbackCmdTest(AgvvRepoTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.runner = CliRunner()

    def test_resolve_repo_uses_agvv_repo_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"AGVV_REPO": "https://github.com/example/demo.git"}, clear=False):
            repo = feedback_cmd._resolve_repo()
        self.assertEqual(repo, "example/demo")

    def test_resolve_repo_falls_back_to_default_repo(self) -> None:
        with mock.patch.dict(os.environ, {"AGVV_REPO": ""}, clear=False):
            repo = feedback_cmd._resolve_repo()
        self.assertEqual(repo, config.DEFAULT_AGVV_REPO)

    def test_feedback_saves_local_file_by_default(self) -> None:
        with mock.patch("agvv.cli.feedback_cmd.subprocess.run") as run_mock:
            result = self.runner.invoke(
                app,
                ["feedback", "--title", "local-only", "--body", "save to ~/.agvv", "--type", "bug"],
            )

        self.assertEqual(result.exit_code, 0)
        run_mock.assert_not_called()
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

        feedback_path = config.feedback_path()
        self.assertTrue(feedback_path.exists())
        entries = json.loads(feedback_path.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "local-only")
        self.assertEqual(entries[0]["body"], "save to ~/.agvv")
        self.assertEqual(entries[0]["type"], "bug")
        self.assertFalse(entries[0]["issue_requested"])
        self.assertNotIn("issue_url", entries[0])

    def test_feedback_with_issue_flag_files_github_issue_and_saves_local_entry(self) -> None:
        gh_result = mock.Mock()
        gh_result.returncode = 0
        gh_result.stdout = "https://github.com/example/demo/issues/42\n"
        gh_result.stderr = ""

        with mock.patch("agvv.cli.feedback_cmd.subprocess.run", return_value=gh_result) as run_mock:
            result = self.runner.invoke(
                app,
                ["feedback", "--title", "file-issue", "--body", "please fix", "--type", "feature", "--issue"],
            )

        self.assertEqual(result.exit_code, 0)
        run_mock.assert_called_once()
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issue"], "https://github.com/example/demo/issues/42")

        entries = json.loads(config.feedback_path().read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["issue_requested"])
        self.assertEqual(entries[0]["issue_repo"], config.DEFAULT_AGVV_REPO)
        self.assertEqual(entries[0]["issue_url"], "https://github.com/example/demo/issues/42")
