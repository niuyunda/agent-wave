"""Prompting and launch command helper tests."""

from __future__ import annotations

from pathlib import Path

from agvv.runtime.models import TaskSpec
from agvv.runtime.prompting import build_launch_command, render_task_prompt


def test_build_launch_command_generates_tty_command_for_codex(
    tmp_path: Path,
) -> None:
    """Test that codex in TTY mode generates a prompt-injection command."""
    prompt_path = tmp_path / "rendered_prompt.md"
    spec = TaskSpec(
        task_id="task_prompt",
        project_name="demo",
        feature="feat_prompt",
        agent_cmd="codex",
        base_dir=tmp_path,
        agent="codex",
        requirements="do something",
    )
    command = build_launch_command(
        spec=spec,
        prompt_path=prompt_path,
        output_log_path=tmp_path / "agent_output.log",
    )
    assert command.startswith("bash -lc ")
    assert "codex" in command
    assert str(prompt_path) in command


def test_render_task_prompt_prefers_requirements_over_legacy_task_doc(
    tmp_path: Path,
) -> None:
    legacy_doc = tmp_path / "legacy.md"
    legacy_doc.write_text("legacy content", encoding="utf-8")
    spec = TaskSpec(
        task_id="task_prompt_pref",
        project_name="demo",
        feature="feat_prompt_pref",
        agent_cmd="codex",
        base_dir=tmp_path,
        requirements="new requirements from task.md body",
        task_doc=str(legacy_doc),
    )
    prompt = render_task_prompt(spec)
    assert "new requirements from task.md body" in prompt
    assert "legacy content" not in prompt


def test_render_task_prompt_falls_back_to_legacy_task_doc(tmp_path: Path) -> None:
    legacy_doc = tmp_path / "legacy.md"
    legacy_doc.write_text("legacy content", encoding="utf-8")
    spec = TaskSpec(
        task_id="task_prompt_legacy",
        project_name="demo",
        feature="feat_prompt_legacy",
        agent_cmd="codex",
        base_dir=tmp_path,
        task_doc=str(legacy_doc),
    )
    prompt = render_task_prompt(spec)
    assert "legacy content" in prompt
