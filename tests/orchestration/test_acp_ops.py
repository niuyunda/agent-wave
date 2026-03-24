"""Tests for acp_ops.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from agvv.orchestration import acp_ops
from agvv.shared.errors import AgvvError


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _fake_result(stdout: str = "", returncode: int = 0):
    """Build a lightweight fake CompletedProcess."""
    return type("R", (), {"stdout": stdout, "returncode": returncode})()


# ------------------------------------------------------------------
# AcpSessionStatus
# ------------------------------------------------------------------


def test_acp_session_status_no_session() -> None:
    status = acp_ops.AcpSessionStatus(
        state="no_session",
        pid=None,
        session_id=None,
        uptime=None,
        last_prompt=None,
        last_exit=None,
    )
    assert status.state == "no_session"
    assert status.pid is None


# ------------------------------------------------------------------
# _parse_status_text
# ------------------------------------------------------------------


def test_parse_status_text_running() -> None:
    text = "\n".join(
        [
            "State: running",
            "PID: 12345",
            "Session ID: sess-abc",
            "Uptime: 5m30s",
            "Last Prompt: 2025-01-01T10:00:00Z",
            "Last Exit: null",
        ]
    )
    status = acp_ops._parse_status_text(text)
    assert status.state == "running"
    assert status.pid == 12345
    assert status.session_id == "sess-abc"
    assert status.uptime == "5m30s"
    assert status.last_prompt == "2025-01-01T10:00:00Z"
    assert status.last_exit is None


def test_parse_status_text_dead() -> None:
    text = "\n".join(
        [
            "State: dead",
            "PID: null",
            "Session ID: sess-abc",
        ]
    )
    status = acp_ops._parse_status_text(text)
    assert status.state == "dead"
    assert status.pid is None


def test_parse_status_text_null_pid_becomes_none() -> None:
    text = "State: running\nPID: null\n"
    status = acp_ops._parse_status_text(text)
    assert status.pid is None


def test_parse_status_text_unknown_state_becomes_no_session() -> None:
    text = "State: whatever\n"
    status = acp_ops._parse_status_text(text)
    assert status.state == "no_session"


def test_parse_status_text_empty_becomes_no_session() -> None:
    status = acp_ops._parse_status_text("")
    assert status.state == "no_session"


# ------------------------------------------------------------------
# acpx_session_status — JSON
# ------------------------------------------------------------------


def test_acpx_session_status_parses_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"running","pid":999,"sessionId":"s1"}')

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        return fake

    status = acp_ops.acpx_session_status("claude", "s1", tmp_path, run_cmd=run_cmd)
    assert status.state == "running"
    assert status.pid == 999
    assert status.session_id == "s1"


# ------------------------------------------------------------------
# acpx_session_status — text fallback
# ------------------------------------------------------------------


def test_acpx_session_status_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called: list[bool] = []

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        called.append(True)
        if len(called) == 1:
            raise RuntimeError("JSON fails")
        return _fake_result(stdout="State: dead\nPID: null\n")

    status = acp_ops.acpx_session_status("codex", "s2", tmp_path, run_cmd=run_cmd)
    assert status.state == "dead"
    assert len(called) == 2


# ------------------------------------------------------------------
# acpx_session_status — all failures
# ------------------------------------------------------------------


def test_acpx_session_status_returns_no_session_on_total_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        raise RuntimeError("everything fails")

    status = acp_ops.acpx_session_status("claude", "s3", tmp_path, run_cmd=run_cmd)
    assert status.state is None


# ------------------------------------------------------------------
# acpx_session_exists
# ------------------------------------------------------------------


def test_acpx_session_exists_true_for_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"running","pid":1}')
    exists = acp_ops.acpx_session_exists(
        "claude", "s1", tmp_path, run_cmd=lambda *a, **k: fake
    )
    assert exists is True


def test_acpx_session_exists_true_for_dead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"dead","pid":null}')
    exists = acp_ops.acpx_session_exists(
        "claude", "s1", tmp_path, run_cmd=lambda *a, **k: fake
    )
    assert exists is True


def test_acpx_session_exists_false_for_no_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"no_session"}')
    exists = acp_ops.acpx_session_exists(
        "claude", "s1", tmp_path, run_cmd=lambda *a, **k: fake
    )
    assert exists is False


# ------------------------------------------------------------------
# acpx_session_running
# ------------------------------------------------------------------


def test_acpx_session_running_true_when_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"running","pid":42}')
    running = acp_ops.acpx_session_running(
        "claude", "s1", tmp_path, run_cmd=lambda *a, **k: fake
    )
    assert running is True


def test_acpx_session_running_false_when_dead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_result(stdout='{"state":"dead"}')
    running = acp_ops.acpx_session_running(
        "claude", "s1", tmp_path, run_cmd=lambda *a, **k: fake
    )
    assert running is False


# ------------------------------------------------------------------
# acpx_create_session
# ------------------------------------------------------------------


def test_acpx_create_session_calls_correct_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["timeout"] = timeout_seconds
        return _fake_result()

    acp_ops.acpx_create_session("claude", "sess-new", tmp_path, run_cmd=run_cmd)
    assert captured["cmd"] == [
        "acpx",
        "claude",
        "sessions",
        "new",
        "--name",
        "sess-new",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 30


# ------------------------------------------------------------------
# acpx_close_session
# ------------------------------------------------------------------


def test_acpx_close_session_calls_correct_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["timeout"] = timeout_seconds
        return _fake_result()

    acp_ops.acpx_close_session("codex", "sess-close", tmp_path, run_cmd=run_cmd)
    assert captured["cmd"] == ["acpx", "codex", "sessions", "close", "sess-close"]
    assert captured["cwd"] == tmp_path
    assert captured["timeout"] == 15


def test_acpx_close_session_ignores_agvverror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Close should not raise if the session is already closed."""

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        raise AgvvError("session already closed")

    # Should not raise
    acp_ops.acpx_close_session("claude", "sess-gone", tmp_path, run_cmd=run_cmd)


# ------------------------------------------------------------------
# acpx_send_prompt
# ------------------------------------------------------------------


def test_acpx_send_prompt_writes_output_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing")
    output_log = tmp_path / "output.log"

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["timeout"] = timeout_seconds
        return _fake_result(stdout="agent output here")

    acp_ops.acpx_send_prompt(
        agent="claude",
        session="sess-run",
        cwd=tmp_path,
        prompt_path=prompt_file,
        output_log_path=output_log,
        timeout_seconds=300,
        run_cmd=run_cmd,
    )

    assert captured["cmd"] == [
        "acpx",
        "--approve-all",
        "claude",
        "-s",
        "sess-run",
        "--file",
        str(prompt_file),
    ]
    assert output_log.read_text() == "agent output here"


def test_acpx_send_prompt_timeout_raises_agvverror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the thing")

    def run_cmd(cmd, cwd=None, timeout_seconds=None):
        raise subprocess.TimeoutExpired(cmd, timeout_seconds or 0)

    with pytest.raises(AgvvError, match="timed out"):
        acp_ops.acpx_send_prompt(
            agent="claude",
            session="sess-run",
            cwd=tmp_path,
            prompt_path=prompt_file,
            timeout_seconds=60,
            run_cmd=run_cmd,
        )
