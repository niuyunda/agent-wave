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

    def test_get_daemon_status_cleans_stale_pid_file(self) -> None:
        config.DAEMON_PID_FILE.write_text("999999\n", encoding="utf-8")

        info = server.get_daemon_status()

        self.assertEqual(info, {"running": False, "pid": None})
        self.assertFalse(config.DAEMON_PID_FILE.exists())
