"""Prompting and output log helper tests."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.models import TaskSpec
from agvv.runtime.prompting import (
    build_launch_command,
    detect_blocking_prompt,
    write_output_summary,
)


def test_write_output_summary_strips_ansi_sequences(tmp_path: Path) -> None:
    worktree = tmp_path / "demo" / "feat"
    agvv_dir = worktree / ".agvv"
    agvv_dir.mkdir(parents=True, exist_ok=True)
    ansi_line = "\x1b[31merror:\x1b[0m build failed"
    (agvv_dir / "agent_output.log").write_text(f"{ansi_line}\n", encoding="utf-8")

    summary_path = write_output_summary(worktree=worktree)
    assert summary_path is not None
    content = summary_path.read_text(encoding="utf-8")
    assert "error: build failed" in content
    assert "\x1b[" not in content


def test_detect_blocking_prompt_matches_known_patterns(tmp_path: Path) -> None:
    worktree = tmp_path / "demo" / "feat"
    agvv_dir = worktree / ".agvv"
    agvv_dir.mkdir(parents=True, exist_ok=True)
    payload = "\x1b[1mDo you trust the contents of this directory?\x1b[0m\nPress enter to continue\n"
    (agvv_dir / "agent_output.log").write_text(payload, encoding="utf-8")

    reason = detect_blocking_prompt(worktree=worktree)
    assert reason == ("trust_confirmation", "trust confirmation prompt")


def test_detect_blocking_prompt_matches_compact_terminal_text(tmp_path: Path) -> None:
    worktree = tmp_path / "demo" / "feat"
    agvv_dir = worktree / ".agvv"
    agvv_dir.mkdir(parents=True, exist_ok=True)
    payload = "Do\x1b[3;6Hyou\x1b[3;10Htrust\x1b[3;16Hthe\x1b[3;20Hcontents\x1b[3;29Hof\x1b[3;32Hthis\x1b[3;37Hdirectory?\n"
    (agvv_dir / "agent_output.log").write_text(payload, encoding="utf-8")

    reason = detect_blocking_prompt(worktree=worktree)
    assert reason == ("trust_confirmation", "trust confirmation prompt")


def test_detect_blocking_prompt_returns_none_for_regular_output(tmp_path: Path) -> None:
    worktree = tmp_path / "demo" / "feat"
    agvv_dir = worktree / ".agvv"
    agvv_dir.mkdir(parents=True, exist_ok=True)
    (agvv_dir / "agent_output.log").write_text(
        "normal execution output\nall good\n", encoding="utf-8"
    )

    assert detect_blocking_prompt(worktree=worktree) is None


def test_build_launch_command_uses_codex_exec_in_non_interactive_mode(
    tmp_path: Path,
) -> None:
    spec = TaskSpec(
        task_id="task_prompt",
        project_name="demo",
        feature="feat_prompt",
        agent_cmd="codex",
        repo="owner/repo",
        base_dir=tmp_path,
        agent="codex",
        agent_non_interactive=True,
    )
    command = build_launch_command(
        spec=spec,
        prompt_path=tmp_path / "rendered_prompt.md",
        output_log_path=tmp_path / "agent_output.log",
    )
    assert "codex exec" in command
