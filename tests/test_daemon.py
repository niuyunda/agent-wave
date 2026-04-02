from __future__ import annotations

import json
from unittest import mock

from agvv.core import config, run, task
from agvv.core.models import RunPurpose, TaskStatus
from agvv.daemon import server

from tests._support import AgvvRepoTestCase


class DaemonTest(AgvvRepoTestCase):
    def tearDown(self) -> None:
        try:
            if server.get_daemon_status()["running"]:
                server.stop_daemon()
        except RuntimeError:
            pass
        super().tearDown()

    def test_start_daemon_returns_ready_pid_from_parent_path(self) -> None:
        proc = mock.Mock()
        proc.pid = 456
        proc.poll.return_value = None

        with (
            mock.patch("agvv.daemon.server.subprocess.Popen", return_value=proc) as popen,
            mock.patch(
                "agvv.daemon.server.get_daemon_status",
                side_effect=[
                    {"running": False, "pid": None},
                    {"running": True, "pid": 456},
                ],
            ),
            mock.patch("agvv.daemon.server.time.monotonic", return_value=0),
            mock.patch("agvv.daemon.server.time.sleep"),
        ):
            pid = server.start_daemon()

        self.assertEqual(pid, 456)
        popen.assert_called_once()

    def test_start_daemon_surfaces_log_tail_on_boot_failure(self) -> None:
        proc = mock.Mock()
        proc.pid = 456
        proc.poll.side_effect = [7]

        with (
            mock.patch("agvv.daemon.server.subprocess.Popen", return_value=proc),
            mock.patch(
                "agvv.daemon.server.get_daemon_status",
                side_effect=[{"running": False, "pid": None}, {"running": False, "pid": None}],
            ),
            mock.patch("agvv.daemon.server._read_daemon_log_tail", return_value="fatal boot error"),
            mock.patch("agvv.daemon.server.time.monotonic", return_value=0),
        ):
            with self.assertRaisesRegex(RuntimeError, "fatal boot error"):
                server.start_daemon()

    def test_determine_exit_status_prefers_runtime_json(self) -> None:
        repo = self._create_project_repo("daemon-runtime-status")
        self._add_task(repo, "runtime-task")

        runtime_file = config.runs_dir(repo, "runtime-task") / "001-implement.runtime.json"
        exitcode_file = config.runs_dir(repo, "runtime-task") / "001-implement.exitcode"
        runtime_file.write_text(json.dumps({"exit_code": 0}) + "\n", encoding="utf-8")
        exitcode_file.write_text("2\n", encoding="utf-8")

        self.assertEqual(
            server._determine_exit_status(repo, "runtime-task").value,
            "completed",
        )
        self.assertTrue(exitcode_file.exists())

    def test_determine_exit_status_consumes_legacy_exitcode_file(self) -> None:
        repo = self._create_project_repo("daemon-exitcode-status")
        self._add_task(repo, "legacy-task")

        exitcode_file = config.runs_dir(repo, "legacy-task") / "001-implement.exitcode"
        exitcode_file.write_text("2\n", encoding="utf-8")

        self.assertEqual(
            server._determine_exit_status(repo, "legacy-task").value,
            "failed",
        )
        self.assertFalse(exitcode_file.exists())

    def test_reconcile_marks_running_task_failed_when_active_run_is_missing(self) -> None:
        repo = self._create_project_repo("daemon-reconcile")
        self._add_task(repo, "stale-task")
        task.update_task_status(repo, "stale-task", TaskStatus.running)

        server._reconcile()

        self.assertEqual(task.show_task(repo, "stale-task")["status"], TaskStatus.failed.value)

    def test_monitor_cycle_times_out_active_run(self) -> None:
        repo = self._create_project_repo("daemon-timeout")
        self._add_task(repo, "timeout-task", "SLEEP=999")

        run.start_run(repo, "timeout-task", RunPurpose.implement, "success")
        active = self._wait_for_active_run(repo, "timeout-task")

        with mock.patch.object(config, "DEFAULT_RUN_TIMEOUT", -1):
            server._monitor_cycle()

        self._wait_for_pid_exit(active["pid"])
        latest = self._latest_run(repo, "timeout-task")
        self.assertEqual(latest["status"], "timed_out")
        self.assertEqual(task.show_task(repo, "timeout-task")["status"], TaskStatus.failed.value)

    def test_monitor_cycle_auto_starts_pending_auto_managed_task(self) -> None:
        repo = self._create_project_repo("daemon-auto-start")
        self._add_task(repo, "auto-task", "SLEEP=999")
        task.mark_task_auto_managed(repo, "auto-task", enabled=True)

        server._monitor_cycle()

        active = self._wait_for_active_run(repo, "auto-task")
        info = task.show_task(repo, "auto-task")
        self.assertEqual(info["status"], TaskStatus.running.value)
        self.assertEqual(info["feedback_status"], "running")
        self.assertEqual(info["runs"][0]["purpose"], "implement")
        self.assertEqual(info["runs"][0]["pid"], active["pid"])

        run.stop_run(repo, "auto-task")

    def test_monitor_cycle_auto_managed_task_completes_with_terminal_feedback(self) -> None:
        repo = self._create_project_repo("daemon-auto-complete")
        self._add_task(repo, "auto-complete-task", "SLEEP=0")
        task.mark_task_auto_managed(repo, "auto-complete-task", enabled=True)

        server._monitor_cycle()
        pid = self._latest_run(repo, "auto-complete-task").get("pid")
        self._wait_for_pid_exit(pid)
        server._monitor_cycle()

        info = task.show_task(repo, "auto-complete-task")
        self.assertEqual(info["status"], TaskStatus.done.value)
        self.assertEqual(info["feedback_status"], "completed")
        self.assertEqual(info["runs"][0]["status"], "completed")

    def test_monitor_cycle_auto_managed_task_uses_project_default_agent(self) -> None:
        repo = self._create_project_repo("daemon-auto-agent")
        self._write_project_config(repo, default_agent="fail")
        self._add_task(repo, "auto-agent-task", "SLEEP=0")
        task.mark_task_auto_managed(repo, "auto-agent-task", enabled=True)

        server._monitor_cycle()
        pid = self._latest_run(repo, "auto-agent-task").get("pid")
        self._wait_for_pid_exit(pid)
        server._monitor_cycle()

        info = task.show_task(repo, "auto-agent-task")
        self.assertEqual(info["status"], TaskStatus.failed.value)
        self.assertEqual(info["feedback_status"], "failed")
        self.assertEqual(info["runs"][0]["agent"], "fail")
        self.assertEqual(info["runs"][0]["status"], "failed")

    def test_monitor_cycle_auto_managed_task_prefers_task_agent_over_project_default(self) -> None:
        repo = self._create_project_repo("daemon-auto-agent-override")
        self._write_project_config(repo, default_agent="fail")

        task_file = self.tmp_path / "auto-agent-override-task.md"
        task_file.write_text(
            "---\nname: auto-agent-override-task\nagent: success\n---\n\nSLEEP=0\n",
            encoding="utf-8",
        )
        task.add_task(repo, task_file)
        task.mark_task_auto_managed(repo, "auto-agent-override-task", enabled=True)

        server._monitor_cycle()
        pid = self._latest_run(repo, "auto-agent-override-task").get("pid")
        self._wait_for_pid_exit(pid)
        server._monitor_cycle()

        info = task.show_task(repo, "auto-agent-override-task")
        self.assertEqual(info["status"], TaskStatus.done.value)
        self.assertEqual(info["feedback_status"], "completed")
        self.assertEqual(info["runs"][0]["agent"], "success")
        self.assertEqual(info["runs"][0]["status"], "completed")

    def test_get_daemon_status_cleans_stale_pid_file(self) -> None:
        config.DAEMON_PID_FILE.write_text("999999\n", encoding="utf-8")

        info = server.get_daemon_status()

        self.assertEqual(info, {"running": False, "pid": None})
        self.assertFalse(config.DAEMON_PID_FILE.exists())
