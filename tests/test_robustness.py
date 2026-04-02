from __future__ import annotations

import os
import signal
import time
import unittest

from agvv.core import run, task
from agvv.core.models import TaskStatus
from agvv.daemon import server
from tests._support import AgvvRepoTestCase


class AgvvRobustnessTest(AgvvRepoTestCase):
    def test_stop_run_kills_uncooperative_process_group(self) -> None:
        repo = self._create_project_repo("stop-uncooperative")
        self._add_task(repo, "stop-task", "SLEEP=999")

        run.start_run(repo, "stop-task", "no_cancel")
        active = self._wait_for_active_run(repo, "stop-task")
        monitor_pid = active["pid"]
        launcher_pid = active["launcher_pid"]

        run.stop_run(repo, "stop-task")
        latest = task.show_task(repo, "stop-task")["runs"][-1]

        self.assertEqual(latest["status"], "stopped")
        self.assertEqual(task.show_task(repo, "stop-task")["status"], "pending")
        self.assertFalse(self._pid_exists(monitor_pid))
        self.assertFalse(self._pid_exists(launcher_pid))

    def test_monitor_cycle_tracks_real_agent_child(self) -> None:
        repo = self._create_project_repo("child-monitoring")
        self._add_task(repo, "child-task", "SLEEP=999")

        run.start_run(repo, "child-task", "no_cancel")
        active = self._wait_for_active_run(repo, "child-task")

        self.assertNotEqual(active["launcher_pid"], active["pid"])
        os.kill(active["launcher_pid"], signal.SIGKILL)
        time.sleep(0.2)

        self.assertTrue(self._pid_exists(active["pid"]))
        server._monitor_cycle()

        still_active = run.get_active_run(repo, "child-task")
        self.assertIsNotNone(still_active)
        self.assertEqual(still_active["status"], "running")

        os.killpg(still_active["pgid"], signal.SIGKILL)
        time.sleep(0.2)
        server._monitor_cycle()

    def test_completed_run_without_checkpoint_becomes_failed(self) -> None:
        repo = self._create_project_repo("missing-checkpoint")
        self._add_task(repo, "checkpoint-task", "SLEEP=1")

        run.start_run(repo, "checkpoint-task", "success")
        worktree_git = repo / "worktrees" / "checkpoint-task" / ".git"
        worktree_git.write_text("BROKEN\n", encoding="utf-8")

        self._wait_for_process_exit(repo, "checkpoint-task")
        server._monitor_cycle()

        latest = task.show_task(repo, "checkpoint-task")["runs"][-1]
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "missing_checkpoint")
        self.assertIsNone(latest.get("checkpoint"))

    def test_merge_conflict_marks_task_blocked_and_reports_files(self) -> None:
        repo = self._create_project_repo("merge-conflict")
        self._add_task(repo, "conflict-a", "SLEEP=1")
        self._add_task(repo, "conflict-b", "SLEEP=1")

        run.start_run(repo, "conflict-a", "success")
        run.start_run(repo, "conflict-b", "success")
        self._wait_for_process_exit(repo, "conflict-a")
        self._wait_for_process_exit(repo, "conflict-b")
        server._monitor_cycle()

        self._commit_in_worktree(repo / "worktrees" / "conflict-a", "src/base.txt", "A-change\n", "conflict A")
        self._commit_in_worktree(repo / "worktrees" / "conflict-b", "src/base.txt", "B-change\n", "conflict B")

        task.merge_task(repo, "conflict-a")
        with self.assertRaises(ValueError) as ctx:
            task.merge_task(repo, "conflict-b")

        self.assertIn("src/base.txt", str(ctx.exception))
        self.assertEqual(task.show_task(repo, "conflict-b")["status"], TaskStatus.blocked.value)

    def test_before_run_hook_failure_rolls_back_fresh_worktree(self) -> None:
        repo = self._create_project_repo("before-run-hook")
        self._add_task(repo, "hook-task", "SLEEP=1")

        hook = repo / "hook-fail.sh"
        hook.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
        hook.chmod(0o755)

        self._write_project_config(repo, hooks={"before_run": str(hook)})

        with self.assertRaises(ValueError):
            run.start_run(repo, "hook-task", "success")

        self.assertFalse((repo / "worktrees" / "hook-task").exists())
        self.assertEqual(task.show_task(repo, "hook-task")["runs"], [])


if __name__ == "__main__":
    unittest.main()
