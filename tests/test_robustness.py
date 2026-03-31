from __future__ import annotations

import os
import signal
import textwrap
import time
import unittest
from unittest import mock

from agvv.core import checkpoint, run, task
from agvv.core.models import RunPurpose, TaskStatus
from agvv.daemon import server
from tests._support import AgvvRepoTestCase

class AgvvRobustnessTest(AgvvRepoTestCase):
    def test_stop_run_kills_uncooperative_process_group(self) -> None:
        repo = self._create_project_repo("stop-uncooperative")
        self._add_task(repo, "stop-task", "SLEEP=999")

        run.start_run(repo, "stop-task", RunPurpose.implement, "no_cancel")
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

        run.start_run(repo, "child-task", RunPurpose.implement, "no_cancel")
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

        run.start_run(repo, "checkpoint-task", RunPurpose.implement, "success")
        worktree_git = repo / "worktrees" / "checkpoint-task" / ".git"
        worktree_git.write_text("BROKEN\n", encoding="utf-8")

        self._wait_for_process_exit(repo, "checkpoint-task")
        server._monitor_cycle()

        latest = task.show_task(repo, "checkpoint-task")["runs"][-1]
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "missing_checkpoint")
        self.assertIsNone(latest.get("checkpoint"))

    def test_checkpoint_show_does_not_hide_latest_failed_run(self) -> None:
        repo = self._create_project_repo("checkpoint-display")
        self._add_task(repo, "display-task", "SLEEP=1")

        run.start_run(repo, "display-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "display-task")
        server._monitor_cycle()

        run.start_run(repo, "display-task", RunPurpose.review, "success")
        worktree_git = repo / "worktrees" / "display-task" / ".git"
        worktree_git.write_text("BROKEN\n", encoding="utf-8")
        self._wait_for_process_exit(repo, "display-task")
        server._monitor_cycle()

        info = checkpoint.show_checkpoint(repo, "display-task")
        self.assertIsNone(info["checkpoint"])
        self.assertEqual(info["latest_run_status"], "failed")
        self.assertIsNotNone(info["previous_checkpoint"])

    def test_merge_conflict_marks_task_blocked_and_reports_files(self) -> None:
        repo = self._create_project_repo("merge-conflict")
        self._add_task(repo, "conflict-a", "SLEEP=1")
        self._add_task(repo, "conflict-b", "SLEEP=1")

        run.start_run(repo, "conflict-a", RunPurpose.implement, "success")
        run.start_run(repo, "conflict-b", RunPurpose.implement, "success")
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
            run.start_run(repo, "hook-task", RunPurpose.implement, "success")

        self.assertFalse((repo / "worktrees" / "hook-task").exists())
        self.assertEqual(task.show_task(repo, "hook-task")["runs"], [])

    def test_review_run_without_report_becomes_failed(self) -> None:
        repo = self._create_project_repo("missing-review-report")
        self._add_task(repo, "review-task", "SLEEP=0")

        agent = self.tmp_path / "no-report-agent.sh"
        agent.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
        agent.chmod(0o755)

        with mock.patch.dict(
            os.environ,
            {"AGVV_ACPX_BIN": str(agent), "AGVV_ACPX_ARGS": "", "AGVV_ACPX_OPTS": ""},
            clear=False,
        ):
            run.start_run(repo, "review-task", RunPurpose.review, "codex")
            self._wait_for_process_exit(repo, "review-task")
            server._monitor_cycle()

        latest = task.show_task(repo, "review-task")["runs"][-1]
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "no_new_checkpoint")

    def test_review_run_with_commit_but_missing_report_is_failed(self) -> None:
        repo = self._create_project_repo("review-commit-no-report")
        self._add_task(repo, "review-task", "SLEEP=0")

        agent = self.tmp_path / "commit-no-report-agent.sh"
        agent.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                while [[ $# -gt 0 ]]; do
                  case "$1" in
                    --approve-all) shift || true ;;
                    --timeout|--model|--cwd|--format) shift 2 || true ;;
                    *) break ;;
                  esac
                done
                shift || true
                while [[ $# -gt 0 ]]; do
                  case "$1" in
                    -s|--session) shift 2 || true ;;
                    --cwd) shift 2 || true ;;
                    --format) shift 2 || true ;;
                    *) break ;;
                  esac
                done
                if [[ "${1:-}" == "sessions" || "${1:-}" == "status" ]]; then
                  if [[ "${1:-}" == "status" ]]; then
                    echo '{"status":"ok"}'
                  fi
                  exit 0
                fi
                printf 'x\\n' >> .agvv-review-only.txt
                git add .agvv-review-only.txt
                git commit -m 'review worktree commit'
                exit 0
                """
            ),
            encoding="utf-8",
        )
        agent.chmod(0o755)

        with mock.patch.dict(
            os.environ,
            {"AGVV_ACPX_BIN": str(agent), "AGVV_ACPX_ARGS": "", "AGVV_ACPX_OPTS": ""},
            clear=False,
        ):
            run.start_run(repo, "review-task", RunPurpose.review, "codex")
            self._wait_for_process_exit(repo, "review-task")
            server._monitor_cycle()

        latest = task.show_task(repo, "review-task")["runs"][-1]
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "missing_review_report")


if __name__ == "__main__":
    unittest.main()
