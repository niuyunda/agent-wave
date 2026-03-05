"""Prompt rendering and launch artifact helpers for coding sessions."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from agvv.runtime.models import TaskSpec, build_agent_command

_TTY_AGENTS = {"codex", "claude_code"}


def agent_requires_tty(spec: TaskSpec) -> bool:
    """Return whether the configured agent should run in an interactive TTY."""
    return (spec.agent or "").strip() in _TTY_AGENTS


def _task_doc_text(spec: TaskSpec) -> str:
    """Read legacy task_doc text when available."""
    if spec.task_doc is None:
        return ""
    try:
        return spec.task_doc.read_text(encoding="utf-8").strip()
    except OSError:
        return f"Task document path: {spec.task_doc}"


def _requirements_text(spec: TaskSpec) -> str:
    """Resolve primary requirement text for prompt construction."""
    if spec.requirements:
        return spec.requirements.strip()
    task_doc = _task_doc_text(spec)
    if task_doc:
        return task_doc
    return f"Complete task {spec.task_id} for branch {spec.feature}."


def render_task_prompt(spec: TaskSpec) -> str:
    """Render a stable task prompt from spec fields."""
    lines = [
        "You are implementing one coding task in this git worktree.",
        "",
        "## Goal",
        _requirements_text(spec),
    ]
    constraints = list(spec.constraints or [])
    if constraints:
        lines.extend(["", "## Constraints"])
        lines.extend(f"- {item}" for item in constraints)
    lines.extend(
        [
            "",
            "## Delivery",
            "- Apply minimal, focused changes.",
            "- Run relevant tests/checks before finishing.",
            "- Commit your changes with a descriptive message.",
            "- Summarize what you changed and the test results.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def write_launch_artifacts(*, worktree: Path, spec: TaskSpec) -> dict[str, Path]:
    """Persist task input snapshot and rendered prompt for auditability."""
    agvv_dir = worktree / ".agvv"
    agvv_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = agvv_dir / "rendered_prompt.md"
    input_snapshot_path = agvv_dir / "input_snapshot.json"
    output_log_path = agvv_dir / "agent_output.log"

    prompt_path.write_text(render_task_prompt(spec), encoding="utf-8")
    input_snapshot = {
        "task_id": spec.task_id,
        "project_name": spec.project_name,
        "feature": spec.feature,
        "repo": spec.repo,
        "base_dir": str(spec.base_dir),
        "requirements": _requirements_text(spec),
        "constraints": list(spec.constraints or []),
        "agent_cmd": spec.agent_cmd,
        "agent_non_interactive": spec.agent_non_interactive,
    }
    input_snapshot_path.write_text(
        json.dumps(input_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "prompt_path": prompt_path,
        "input_snapshot_path": input_snapshot_path,
        "output_log_path": output_log_path,
    }


def _codex_has_sandbox_flag(extra_args: list[str]) -> bool:
    """Return True if user already specified a sandbox flag in extra_args."""
    return "-s" in extra_args or "--sandbox" in extra_args


def build_launch_command(
    *, spec: TaskSpec, prompt_path: Path, output_log_path: Path
) -> str:
    """Build wrapped agent command with prompt injection and output logging."""
    agent_cmd = spec.agent_cmd.strip()
    prompt_arg = f'"$(cat {shlex.quote(str(prompt_path))})"'
    extra_args = list(spec.agent_extra_args or [])
    default_cmd = build_agent_command(
        provider=spec.agent or "codex",
        model=spec.agent_model,
        extra_args=extra_args,
    )
    if agent_requires_tty(spec):
        if agent_cmd == default_cmd:
            if spec.agent_non_interactive and (spec.agent or "codex") == "codex":
                parts = shlex.split(agent_cmd)
                if parts and parts[0] == "codex":
                    if not _codex_has_sandbox_flag(extra_args):
                        parts = [parts[0], "exec", "-s", "workspace-write", *parts[1:]]
                    else:
                        parts = [parts[0], "exec", *parts[1:]]
                    non_interactive_cmd = shlex.join(parts)
                    script = f"{non_interactive_cmd} {prompt_arg}"
                else:
                    script = f"{agent_cmd} {prompt_arg}"
            else:
                script = f"{agent_cmd} {prompt_arg}"
        else:
            script = agent_cmd
    else:
        log_redirect = f"2>&1 | tee -a {shlex.quote(str(output_log_path))}"
        if agent_cmd == default_cmd:
            script = f"{agent_cmd} {prompt_arg} {log_redirect}"
        else:
            script = f"{agent_cmd} {log_redirect}"
    return f"bash -lc {shlex.quote(script)}"
