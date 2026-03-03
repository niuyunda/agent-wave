from __future__ import annotations

from pathlib import Path

import pytest

from agvv.orchestration import AgvvError, tmux_new_session
from agvv.orchestration.tmux_ops import tmux_kill_session, tmux_session_exists


def test_tmux_new_session_uses_tmux_cwd_and_preserves_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr("agvv.orchestration.tmux_ops.tmux_session_exists", lambda _session: False)

    def _fake_run(cmd: list[str], cwd: Path | None = None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.orchestration.tmux_ops._run", _fake_run)
    tmux_new_session(session="sess-a", cwd=tmp_path, command="codex --model gpt-5 --approval-mode auto")
    assert captured["cwd"] is None
    assert captured["cmd"] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "sess-a",
        "-c",
        str(tmp_path.resolve()),
        "exec codex --model gpt-5 --approval-mode auto",
    ]


def test_tmux_new_session_rejects_empty_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("agvv.orchestration.tmux_ops.tmux_session_exists", lambda _session: False)
    with pytest.raises(AgvvError, match="tmux command cannot be empty"):
        tmux_new_session(session="sess-a", cwd=tmp_path, command="   ")


def test_tmux_session_exists_raises_when_tmux_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agvv.orchestration.tmux_ops.subprocess.run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("tmux")))
    with pytest.raises(AgvvError, match="tmux not found"):
        tmux_session_exists("sess-missing")


def test_tmux_kill_session_noops_when_session_absent() -> None:
    calls: list[list[str]] = []
    tmux_kill_session(
        "sess-absent",
        run_cmd=lambda cmd, cwd=None: calls.append(list(cmd)),
        session_exists=lambda _session: False,
    )
    assert calls == []


def test_tmux_kill_session_invokes_runner_when_session_present() -> None:
    calls: list[list[str]] = []
    tmux_kill_session(
        "sess-live",
        run_cmd=lambda cmd, cwd=None: calls.append(list(cmd)),
        session_exists=lambda _session: True,
    )
    assert calls == [["tmux", "kill-session", "-t", "sess-live"]]
