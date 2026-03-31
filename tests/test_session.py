from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from agvv.core import session


class SessionTest(unittest.TestCase):
    def test_ensure_session_uses_preferred_order_first(self) -> None:
        with (
            mock.patch("agvv.core.session.acpx_invocation", return_value=("acpx", [])),
            mock.patch("agvv.core.session.subprocess.run", return_value=subprocess.CompletedProcess(["ok"], 0)) as run_mock,
        ):
            ok = session.ensure_session(Path("/repo"), "task-a", "codex")

        self.assertTrue(ok)
        self.assertEqual(run_mock.call_count, 1)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:4], ["acpx", "--cwd", "/repo/worktrees/task-a", "codex"])

    def test_ensure_session_falls_back_to_legacy_order(self) -> None:
        preferred_err = subprocess.CalledProcessError(2, ["acpx"])
        with (
            mock.patch("agvv.core.session.acpx_invocation", return_value=("acpx", [])),
            mock.patch(
                "agvv.core.session.subprocess.run",
                side_effect=[preferred_err, subprocess.CompletedProcess(["ok"], 0)],
            ) as run_mock,
        ):
            ok = session.ensure_session(Path("/repo"), "task-b", "codex")

        self.assertTrue(ok)
        self.assertEqual(run_mock.call_count, 2)
        preferred_cmd = run_mock.call_args_list[0].args[0]
        legacy_cmd = run_mock.call_args_list[1].args[0]
        self.assertEqual(preferred_cmd[:4], ["acpx", "--cwd", "/repo/worktrees/task-b", "codex"])
        self.assertEqual(legacy_cmd[:4], ["acpx", "codex", "--cwd", "/repo/worktrees/task-b"])

    def test_get_session_status_parses_text_output(self) -> None:
        with (
            mock.patch("agvv.core.session.acpx_invocation", return_value=("acpx", [])),
            mock.patch(
                "agvv.core.session.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["acpx"],
                    0,
                    stdout="session: abc\nstatus: dead\npid: 123\n",
                    stderr="",
                ),
            ),
        ):
            info = session.get_session_status(Path("/repo"), "task-c", "codex")

        assert info is not None
        self.assertEqual(info["session"], "abc")
        self.assertEqual(info["status"], "dead")
        self.assertEqual(info["pid"], "123")

    def test_cancel_session_uses_worktree_scoped_command(self) -> None:
        with (
            mock.patch("agvv.core.session.acpx_invocation", return_value=("acpx", [])),
            mock.patch(
                "agvv.core.session.subprocess.run",
                return_value=subprocess.CompletedProcess(["acpx"], 0),
            ) as run_mock,
        ):
            ok = session.cancel_session(Path("/repo"), "task-d", "codex")

        self.assertTrue(ok)
        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:4], ["acpx", "--cwd", "/repo/worktrees/task-d", "codex"])
        self.assertEqual(cmd[4:], ["-s", "task-d", "cancel"])
