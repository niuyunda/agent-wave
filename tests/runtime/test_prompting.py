"""Prompting and launch command helper tests."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.models import TaskSpec
from agvv.runtime.prompting import build_launch_command


def test_build_launch_command_uses_codex_exec_in_non_interactive_mode(tmp_path: Path) -> None:
    spec = TaskSpec(
        task_id="task_prompt",
        project_name="demo",
        feature="feat_prompt",
        agent_cmd="codex",
        base_dir=tmp_path,
        agent="codex",
        agent_non_interactive=True,
        requirements="do something",
    )
    command = build_launch_command(
        spec=spec,
        prompt_path=tmp_path / "rendered_prompt.md",
        output_log_path=tmp_path / "agent_output.log",
    )
    assert "codex exec" in command
