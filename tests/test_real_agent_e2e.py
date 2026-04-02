from __future__ import annotations

import os
import shutil
import textwrap
import unittest
from unittest import mock

import frontmatter

from agvv.core import run, task
from agvv.core.models import TaskStatus
from agvv.daemon import server
from agvv.utils import git

from tests._support import AgvvRepoTestCase


RUN_REAL_AGENT_E2E = os.environ.get("AGVV_RUN_REAL_AGENT_E2E") == "1"


@unittest.skipUnless(
    RUN_REAL_AGENT_E2E,
    "set AGVV_RUN_REAL_AGENT_E2E=1 to run the real acpx->codex end-to-end test",
)
class RealAgentE2ETest(AgvvRepoTestCase):
    def test_acpx_codex_run_completes_and_creates_checkpoint(self) -> None:
        if not shutil.which("acpx"):
            self.skipTest("acpx is not installed")

        repo = self._create_project_repo("real-agent-e2e")
        task_name = "real-agent-task"
        marker = "AGVV_REAL_AGENT_OK"

        task_file = self.tmp_path / f"{task_name}.md"
        task_file.write_text(
            frontmatter.dumps(
                frontmatter.Post(
                    textwrap.dedent(
                        f"""\
                        ## Goal
                        Update README.md in the repository root.

                        ## Requirements
                        - Append a new line containing exactly `{marker}`.
                        - Create a git commit for the change.
                        - Do not modify any other files.
                        """
                    ),
                    name=task_name,
                )
            )
            + "\n",
            encoding="utf-8",
        )
        task.add_task(repo, task_file)

        with mock.patch.dict(
            os.environ,
            {
                "AGVV_ACPX_BIN": "acpx",
                "AGVV_ACPX_ARGS": "--approve-all --timeout 180",
            },
            clear=False,
        ):
            run.start_run(repo, task_name, "codex")
            self._wait_for_process_exit(repo, task_name, timeout=300.0)
            server._monitor_cycle()

        latest = self._latest_run(repo, task_name)
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["agent"], "codex")
        self.assertEqual(latest["exit_code"], 0)
        self.assertIsNotNone(latest["checkpoint"])
        self.assertEqual(task.show_task(repo, task_name)["status"], TaskStatus.pending.value)

        worktree_readme = repo / "worktrees" / task_name / "README.md"
        self.assertIn(marker, worktree_readme.read_text(encoding="utf-8"))
        commit_files = git.run_git(
            ["show", "--name-only", "--format=", latest["checkpoint"]],
            cwd=repo,
        ).splitlines()
        self.assertEqual([path for path in commit_files if path], ["README.md"])
