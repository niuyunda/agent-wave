"""Prompt rendering and launch artifact helpers for coding sessions."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from agvv.runtime.models import TaskSpec, build_agent_command

_TTY_AGENTS = {"codex", "claude_code"}
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_COMPACT_NON_ALNUM_RE = re.compile(r"[^a-z0-9?]+")
_BLOCKING_PROMPT_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("trust_confirmation", "trust confirmation prompt", "doyoutrustthecontentsofthisdirectory?"),
    ("interactive_continue", "interactive continue prompt", "pressentertocontinue"),
)


def agent_requires_tty(spec: TaskSpec) -> bool:
    """Return whether the configured agent should run in an interactive TTY."""

    return (spec.agent or "").strip() in _TTY_AGENTS


def strip_ansi_sequences(text: str) -> str:
    """Remove common ANSI terminal control sequences from text."""

    return _ANSI_ESCAPE_RE.sub("", text)


def _compact_text(text: str) -> str:
    """Compact free-form terminal text for resilient substring matching."""

    lowered = strip_ansi_sequences(text).lower()
    return _COMPACT_NON_ALNUM_RE.sub("", lowered)


def _effective_acceptance_criteria(spec: TaskSpec) -> list[str]:
    """Return explicit criteria or a stable default fallback."""

    if spec.acceptance_criteria:
        return list(spec.acceptance_criteria)
    return [
        "Relevant tests/checks pass for changed scope.",
        "Changed files and verification results are summarized.",
    ]


def _task_doc_text(spec: TaskSpec) -> str:
    """Read task document text when available."""

    if spec.task_doc is None:
        return ""
    try:
        return spec.task_doc.read_text(encoding="utf-8").strip()
    except OSError:
        return f"Task document path: {spec.task_doc}"


def _requirements_text(spec: TaskSpec) -> str:
    """Resolve primary requirement text for prompt construction."""

    task_doc = _task_doc_text(spec)
    if task_doc:
        return task_doc
    if spec.requirements:
        return spec.requirements.strip()
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
    acceptance_criteria = _effective_acceptance_criteria(spec)
    if acceptance_criteria:
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in acceptance_criteria)
    lines.extend(
        [
            "",
            "## Delivery",
            "- Apply minimal, focused changes.",
            "- Run relevant tests/checks before finishing.",
            "- Summarize changed files and verification results.",
            "- Write `.agvv/dod_result.json` with pass/fail evidence for every acceptance criterion.",
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
        "acceptance_criteria": _effective_acceptance_criteria(spec),
        "agent_cmd": spec.agent_cmd,
        "agent_non_interactive": spec.agent_non_interactive,
    }
    input_snapshot_path.write_text(json.dumps(input_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "prompt_path": prompt_path,
        "input_snapshot_path": input_snapshot_path,
        "output_log_path": output_log_path,
    }


def build_launch_command(*, spec: TaskSpec, prompt_path: Path, output_log_path: Path) -> str:
    """Build wrapped agent command with prompt injection and output logging."""

    agent_cmd = spec.agent_cmd.strip()
    prompt_arg = f'"$(cat {shlex.quote(str(prompt_path))})"'
    default_cmd = build_agent_command(
        provider=spec.agent or "codex",
        model=spec.agent_model,
        extra_args=list(spec.agent_extra_args or []),
    )
    if agent_requires_tty(spec):
        if agent_cmd == default_cmd:
            if spec.agent_non_interactive and (spec.agent or "codex") == "codex":
                parts = shlex.split(agent_cmd)
                if parts and parts[0] == "codex":
                    non_interactive_cmd = shlex.join([parts[0], "exec", *parts[1:]])
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


def write_output_summary(*, worktree: Path, max_lines: int = 80) -> Path | None:
    """Write a lightweight summary file from the captured output log."""

    output_log = worktree / ".agvv" / "agent_output.log"
    if not output_log.exists():
        return None
    try:
        raw_lines = output_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    tail_lines = raw_lines[-max_lines:]
    summary_lines = [strip_ansi_sequences(line) for line in tail_lines]
    summary_lines = [line for line in summary_lines if line.strip()]
    summary_path = worktree / ".agvv" / "agent_output_summary.txt"
    if not summary_lines:
        summary_path.write_text("No non-empty output lines captured.\n", encoding="utf-8")
        return summary_path
    summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
    return summary_path


def detect_blocking_prompt(*, worktree: Path, max_scan_chars: int = 32768) -> tuple[str, str] | None:
    """Detect known interactive prompts that block unattended agent sessions."""

    output_log = worktree / ".agvv" / "agent_output.log"
    if not output_log.exists():
        return None
    try:
        raw_text = output_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    scan_text = _compact_text(raw_text[-max_scan_chars:])
    if not scan_text:
        return None
    for code, label, pattern in _BLOCKING_PROMPT_PATTERNS:
        if pattern in scan_text:
            return code, label
    return None


def validate_dod_result(*, worktree: Path, spec: TaskSpec) -> tuple[bool, str]:
    """Validate machine-readable DoD result file for task completion."""

    expected = _effective_acceptance_criteria(spec)
    result_path = worktree / ".agvv" / "dod_result.json"
    if not result_path.exists():
        return False, f"Missing DoD result file: {result_path}"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Invalid DoD result JSON at {result_path}: {exc}"
    if not isinstance(payload, dict):
        return False, "DoD result must be a JSON object."
    criteria = payload.get("criteria")
    if not isinstance(criteria, list):
        return False, "DoD result field 'criteria' must be a list."
    rows: dict[str, str] = {}
    for row in criteria:
        if not isinstance(row, dict):
            return False, "Each DoD criteria entry must be an object."
        item = str(row.get("item", "")).strip()
        status = str(row.get("status", "")).strip().lower()
        if not item:
            return False, "DoD criteria entry missing non-empty 'item'."
        if status not in {"pass", "ok", "done"}:
            return False, f"DoD criterion '{item}' is not passing (status={status!r})."
        rows[item] = status
    missing = [item for item in expected if item not in rows]
    if missing:
        return False, f"DoD result missing acceptance criteria: {', '.join(missing)}"
    return True, f"Validated {len(expected)} acceptance criteria from {result_path}."
