from __future__ import annotations

import os
import shlex
from unittest import mock

from agvv.core import config, run, task
from agvv.core.acpx import acpx_invocation
from agvv.core.models import RunPurpose, TaskStatus
from agvv.daemon import server
from agvv.utils import git

from tests._support import AgvvRepoTestCase


class RunTest(AgvvRepoTestCase):
    def test_acpx_invocation_prefers_local_binary_when_not_overridden(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("agvv.core.acpx.shutil.which", return_value="/usr/local/bin/acpx"),
        ):
            invocation = acpx_invocation()

        self.assertEqual(invocation, ("/usr/local/bin/acpx", []))

    def test_build_acpx_prompt_command_uses_runtime_environment(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"AGVV_ACPX_BIN": "launcher", "AGVV_ACPX_ARGS": "agent-wrapper --fast"},
            clear=False,
        ):
            command = run._build_acpx_prompt_command("codex", "session-a", "prompt body")

        self.assertEqual(
            command,
            ["launcher", "agent-wrapper", "--fast", "codex", "-s", "session-a", "prompt body"],
        )

    def test_get_active_run_ignores_runtime_finished_process(self) -> None:
        repo = self._create_project_repo("run-finished-runtime")
        self._add_task(repo, "finished-runtime-task", "SLEEP=0")

        run.start_run(repo, "finished-runtime-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "finished-runtime-task")

        self.assertIsNone(run.get_active_run(repo, "finished-runtime-task"))
        self.assertEqual(run.list_runs(repo), [])

    def test_list_runs_reconciles_completed_runtime_without_daemon_cycle(self) -> None:
        repo = self._create_project_repo("run-self-reconcile")
        task_name = "self-reconcile-task"
        self._add_task(repo, task_name, "SLEEP=0")

        run.start_run(repo, task_name, RunPurpose.implement, "success")
        pid = self._latest_run(repo, task_name)["pid"]
        self._wait_for_pid_exit(pid)

        # Before reconciliation, task state can still be "running".
        self.assertEqual(task.show_task(repo, task_name)["status"], TaskStatus.running.value)

        self.assertEqual(run.list_runs(repo), [])
        latest = self._latest_run(repo, task_name)
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(task.show_task(repo, task_name)["status"], TaskStatus.pending.value)

    def test_failed_run_captures_agent_log_tail(self) -> None:
        repo = self._create_project_repo("run-failure-log")
        self._add_task(repo, "failure-log-task", "Investigate failure.")

        failing_agent = self.tmp_path / "failing-agent.sh"
        failing_agent.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "echo 'No acpx session found for failure-log-task' >&2\n"
            "exit 4\n",
            encoding="utf-8",
        )
        failing_agent.chmod(0o755)

        with mock.patch.dict(
            os.environ,
            {"AGVV_ACPX_BIN": str(failing_agent), "AGVV_ACPX_ARGS": ""},
            clear=False,
        ):
            run.start_run(repo, "failure-log-task", RunPurpose.implement, "codex")
            self._wait_for_process_exit(repo, "failure-log-task")
            server._monitor_cycle()

        latest = self._latest_run(repo, "failure-log-task")
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["exit_code"], 4)
        self.assertIn("No acpx session found", latest.get("error_message", ""))

    def test_start_run_runs_hooks_and_records_completed_metadata(self) -> None:
        repo = self._create_project_repo("run-hooks")
        self._add_task(repo, "hooked-task", "SLEEP=0")

        log_file = self.tmp_path / "hook.log"
        hook_script = self.tmp_path / "record-hook.sh"
        hook_script.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$1\" >> \"$2\"\n",
            encoding="utf-8",
        )
        hook_script.chmod(0o755)
        self._write_project_config(
            repo,
            hooks={
                "after_create": f"{shlex.quote(str(hook_script))} after_create {shlex.quote(str(log_file))}",
                "before_run": f"{shlex.quote(str(hook_script))} before_run {shlex.quote(str(log_file))}",
                "after_run": f"{shlex.quote(str(hook_script))} after_run {shlex.quote(str(log_file))}",
            },
        )

        run.start_run(repo, "hooked-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "hooked-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "hooked-task")
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["exit_code"], 0)
        self.assertIsNotNone(latest["checkpoint"])
        self.assertEqual(task.show_task(repo, "hooked-task")["status"], TaskStatus.pending.value)
        self.assertEqual(
            log_file.read_text(encoding="utf-8").splitlines(),
            ["after_create", "before_run", "after_run"],
        )

    def test_start_run_reuses_existing_worktree_without_repeating_after_create(self) -> None:
        repo = self._create_project_repo("run-reuse")
        self._add_task(repo, "reuse-task", "SLEEP=0")

        log_file = self.tmp_path / "reuse-hooks.log"
        hook_script = self.tmp_path / "record-reuse-hook.sh"
        hook_script.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$1\" >> \"$2\"\n",
            encoding="utf-8",
        )
        hook_script.chmod(0o755)
        self._write_project_config(
            repo,
            hooks={
                "after_create": f"{shlex.quote(str(hook_script))} after_create {shlex.quote(str(log_file))}",
                "before_run": f"{shlex.quote(str(hook_script))} before_run {shlex.quote(str(log_file))}",
                "after_run": f"{shlex.quote(str(hook_script))} after_run {shlex.quote(str(log_file))}",
            },
        )

        run.start_run(repo, "reuse-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "reuse-task")
        server._monitor_cycle()

        run.start_run(repo, "reuse-task", RunPurpose.review, "success")
        self._wait_for_process_exit(repo, "reuse-task")
        server._monitor_cycle()

        self.assertTrue((repo / "worktrees" / "reuse-task").exists())
        self.assertEqual(
            log_file.read_text(encoding="utf-8").splitlines(),
            ["after_create", "before_run", "after_run", "before_run", "after_run"],
        )
        self.assertEqual(len(task.show_task(repo, "reuse-task")["runs"]), 2)

    def test_failed_run_records_exit_code_and_failed_task_status(self) -> None:
        repo = self._create_project_repo("run-failure")
        self._add_task(repo, "failing-task", "SLEEP=0")

        run.start_run(repo, "failing-task", RunPurpose.test, "fail")
        self._wait_for_process_exit(repo, "failing-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "failing-task")
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["exit_code"], 2)
        self.assertIsNone(latest["checkpoint"])
        self.assertEqual(task.show_task(repo, "failing-task")["status"], TaskStatus.failed.value)

    def test_list_runs_returns_only_currently_running_tasks(self) -> None:
        repo = self._create_project_repo("run-listing")
        self._add_task(repo, "long-run", "SLEEP=999")
        self._add_task(repo, "finished-run", "SLEEP=0")

        run.start_run(repo, "long-run", RunPurpose.implement, "success")
        active = self._wait_for_active_run(repo, "long-run")
        run.start_run(repo, "finished-run", RunPurpose.review, "success")
        self._wait_for_process_exit(repo, "finished-run")
        server._monitor_cycle()

        active_runs = run.list_runs(repo)
        self.assertEqual([entry["task"] for entry in active_runs], ["long-run"])
        self.assertEqual(active_runs[0]["pid"], active["pid"])

        run.stop_run(repo, "long-run")

    def test_completed_implement_run_without_new_commit_is_failed(self) -> None:
        repo = self._create_project_repo("run-no-new-checkpoint")
        self._add_task(repo, "no-new-checkpoint-task", "SLEEP=0")

        run.start_run(repo, "no-new-checkpoint-task", RunPurpose.implement, "no_commit")
        self._wait_for_process_exit(repo, "no-new-checkpoint-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "no-new-checkpoint-task")
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "no_new_checkpoint")
        self.assertIsNone(latest["checkpoint"])
        self.assertEqual(
            task.show_task(repo, "no-new-checkpoint-task")["status"],
            TaskStatus.failed.value,
        )

    def test_completed_test_run_without_new_commit_is_failed(self) -> None:
        repo = self._create_project_repo("run-test-no-new-checkpoint")
        self._add_task(repo, "test-no-new-cp-task", "SLEEP=0")

        run.start_run(repo, "test-no-new-cp-task", RunPurpose.test, "no_commit")
        self._wait_for_process_exit(repo, "test-no-new-cp-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "test-no-new-cp-task")
        self.assertEqual(latest["status"], "failed")
        self.assertEqual(latest["finish_reason"], "no_new_checkpoint")
        self.assertIsNone(latest.get("checkpoint"))

    def test_review_run_supports_base_branch_and_writes_report(self) -> None:
        repo = self._create_project_repo("review-base-branch")
        self._add_task(repo, "review-task", "SLEEP=0")

        self._run(["git", "checkout", "-b", "feature-branch"], cwd=repo)
        (repo / "src" / "feature.txt").write_text("feature\n", encoding="utf-8")
        self._run(["git", "add", "src/feature.txt"], cwd=repo)
        self._run(["git", "commit", "-m", "feature commit"], cwd=repo)
        self._run(["git", "checkout", "main"], cwd=repo)

        run.start_run(
            repo,
            "review-task",
            RunPurpose.review,
            "success",
            base_branch="feature-branch",
        )
        self._wait_for_process_exit(repo, "review-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "review-task")
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["base_branch"], "feature-branch")
        feature_tip = git.run_git(["rev-parse", "feature-branch"], cwd=repo)
        self.assertIsNotNone(latest["checkpoint"])
        self.assertNotEqual(latest["checkpoint"], feature_tip)
        report_path = latest.get("report_path")
        self.assertIsNotNone(report_path)

        wt = repo / "worktrees" / "review-task"
        self.assertEqual(git.current_branch(wt), "HEAD")
        self.assertEqual(git.get_latest_commit(wt), latest["checkpoint"])
        self.assertFalse(git.ref_exists(repo, "agvv/review-task"))
        self.assertTrue((wt / report_path).exists())

    def test_implement_run_reattaches_task_branch_after_detached_review(self) -> None:
        repo = self._create_project_repo("review-to-implement")
        self._add_task(repo, "reattach-task", "SLEEP=0")

        run.start_run(repo, "reattach-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "reattach-task")
        server._monitor_cycle()

        branch_tip_before = git.run_git(["rev-parse", "agvv/reattach-task"], cwd=repo)

        run.start_run(repo, "reattach-task", RunPurpose.review, "success")
        self._wait_for_process_exit(repo, "reattach-task")
        server._monitor_cycle()

        wt = repo / "worktrees" / "reattach-task"
        self.assertEqual(git.current_branch(wt), "HEAD")

        run.start_run(repo, "reattach-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "reattach-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "reattach-task")
        branch_tip_after = git.run_git(["rev-parse", "agvv/reattach-task"], cwd=repo)

        self.assertEqual(latest["status"], "completed")
        self.assertEqual(git.current_branch(wt), "agvv/reattach-task")
        self.assertEqual(branch_tip_after, latest["checkpoint"])
        self.assertEqual(git.get_latest_commit(wt), latest["checkpoint"])
        self.assertNotEqual(branch_tip_after, branch_tip_before)

    def test_repair_run_respects_base_branch_checkpoint(self) -> None:
        repo = self._create_project_repo("repair-base-branch")
        self._add_task(repo, "impl-task", "SLEEP=0")
        self._add_task(repo, "repair-task", "SLEEP=0")

        run.start_run(repo, "impl-task", RunPurpose.implement, "success")
        self._wait_for_process_exit(repo, "impl-task")
        server._monitor_cycle()

        impl_tip = git.run_git(["rev-parse", "agvv/impl-task"], cwd=repo)
        main_head = git.run_git(["rev-parse", "main"], cwd=repo)
        self.assertNotEqual(impl_tip, main_head)

        run.start_run(
            repo,
            "repair-task",
            RunPurpose.repair,
            "success",
            base_branch="agvv/impl-task",
        )
        self._wait_for_process_exit(repo, "repair-task")
        server._monitor_cycle()

        latest = self._latest_run(repo, "repair-task")
        self.assertEqual(latest["status"], "completed")
        self.assertEqual(latest["base_branch"], "agvv/impl-task")
        self.assertEqual(latest["base_commit"], impl_tip)

        repair_wt = repo / "worktrees" / "repair-task"
        self.assertTrue(git.ref_exists(repo, "agvv/repair-task"))
        self.assertEqual(git.current_branch(repair_wt), "agvv/repair-task")
        repair_tip = git.get_latest_commit(repair_wt)
        self.assertNotEqual(repair_tip, impl_tip)
        self.assertEqual(latest["checkpoint"], repair_tip)
