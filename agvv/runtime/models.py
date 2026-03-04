"""Task state and specification models."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agvv.shared.errors import AgvvError

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_AGENT_PROVIDER_ALIASES = {
    "codex": "codex",
    "claude": "claude_code",
    "claude_code": "claude_code",
    "claude-code": "claude_code",
}


def _generate_task_id(project_name: str, feature: str) -> str:
    """Generate runtime task id from project and feature."""

    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{project_name}-{feature}-{stamp}"


class TaskState(str, Enum):
    """Lifecycle states for the task state machine."""

    PENDING = "pending"
    CODING = "coding"
    PR_OPEN = "pr_open"
    PR_MERGED = "pr_merged"
    PR_CLOSED = "pr_closed"
    TIMED_OUT = "timed_out"
    CLEANED = "cleaned"
    FAILED = "failed"
    BLOCKED = "blocked"


TERMINAL_STATES = {
    TaskState.PR_MERGED,
    TaskState.PR_CLOSED,
    TaskState.TIMED_OUT,
    TaskState.CLEANED,
    TaskState.FAILED,
    TaskState.BLOCKED,
}
ACTIVE_STATES = {TaskState.PENDING, TaskState.CODING, TaskState.PR_OPEN}
RECOVERABLE_RETRY_STATES = {
    TaskState.FAILED,
    TaskState.TIMED_OUT,
    TaskState.BLOCKED,
    TaskState.CODING,
}


def _coerce_bool(value: Any, default: bool) -> bool:
    """Convert user-provided values into booleans with a default fallback."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise AgvvError(f"Invalid boolean value: {value!r}")


def _coerce_int(value: Any, label: str, default: int, min_value: int = 0) -> int:
    """Convert user-provided values into bounded integers."""

    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AgvvError(f"{label} must be an integer, got: {value!r}") from exc
    if parsed < min_value:
        raise AgvvError(f"{label} must be >= {min_value}, got: {parsed}")
    return parsed


def _coerce_agent_extra_args(value: Any, label: str) -> list[str]:
    """Validate agent extra args as a list of non-empty strings."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise AgvvError(f"{label} must be a list.")
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AgvvError(f"{label} must contain only strings.")
        normalized = item.strip()
        if not normalized:
            raise AgvvError(f"{label} must not contain empty values.")
        parsed.append(normalized)
    return parsed


def _coerce_string_list(value: Any, label: str) -> list[str]:
    """Validate a string list field with non-empty normalized values."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise AgvvError(f"{label} must be a list.")
    parsed: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AgvvError(f"{label} must contain only strings.")
        normalized = item.strip()
        if not normalized:
            raise AgvvError(f"{label} must not contain empty values.")
        parsed.append(normalized)
    return parsed


def _normalize_acceptance_criteria(value: Any) -> list[str]:
    """Normalize acceptance criteria to a bounded machine-readable checklist."""

    parsed = _coerce_string_list(value, "Task spec field 'acceptance_criteria'")
    if not parsed:
        return [
            "Relevant tests/checks pass for changed scope.",
            "Changed files and verification results are summarized.",
        ]
    if len(parsed) < 2 or len(parsed) > 5:
        raise AgvvError("Task spec field 'acceptance_criteria' must contain 2-5 items.")
    return parsed


def _coerce_task_doc_path(value: Any, spec_dir: Path | None = None) -> Path | None:
    """Normalize optional task_doc path from payload data.

    Relative paths are resolved against ``spec_dir`` (the directory containing
    the spec file) when provided, falling back to CWD otherwise.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise AgvvError("Task spec field 'task_doc' must be a string path.")
    normalized = value.strip()
    if not normalized:
        return None
    p = Path(normalized).expanduser()
    if not p.is_absolute() and spec_dir is not None:
        return (spec_dir / p).resolve()
    return p.resolve()


def normalize_agent_provider(value: str | None) -> str:
    """Normalize provider aliases into canonical provider identifiers."""

    raw = (value or "codex").strip()
    if not raw:
        raw = "codex"
    key = raw.lower().replace("-", "_")
    provider = _AGENT_PROVIDER_ALIASES.get(key)
    if provider is None:
        supported = ", ".join(sorted(set(_AGENT_PROVIDER_ALIASES.values())))
        raise AgvvError(f"Unsupported agent provider '{raw}'. Supported providers: {supported}.")
    return provider


def build_agent_command(provider: str, model: str | None, extra_args: list[str]) -> str:
    """Build a shell-safe command line for the configured coding agent."""

    if provider == "codex":
        parts = ["codex"]
    elif provider == "claude_code":
        parts = ["claude", "code"]
    else:
        raise AgvvError(f"Unsupported agent provider '{provider}'.")

    if model:
        parts.extend(["--model", model])
    parts.extend(extra_args)
    return shlex.join(parts)


@dataclass(frozen=True)
class TaskSpec:
    """Task spec consumed by the state machine."""

    task_id: str
    project_name: str
    feature: str
    agent_cmd: str
    repo: str
    base_dir: Path
    from_branch: str = "main"
    session: str | None = None
    agent: str | None = "codex"
    agent_model: str | None = None
    agent_extra_args: list[str] | None = None
    agent_non_interactive: bool = True
    ticket: str | None = None
    task_doc: Path | None = None
    requirements: str | None = None
    constraints: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    params: dict[str, str] | None = None
    create_dirs: list[str] | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    pr_base: str = "main"
    branch_remote: str = "origin"
    max_retry_cycles: int = 5
    timeout_minutes: int = 240
    auto_cleanup: bool = True
    keep_branch_on_cleanup: bool = False
    commit_message: str | None = None

    def normalized_session(self) -> str:
        """Return a deterministic tmux session name for the task."""

        return self.session or f"agvv-{self.task_id}"

    def to_payload(self) -> dict[str, Any]:
        """Serialize this spec into JSON-safe primitives."""

        extra_args = list(self.agent_extra_args) if self.agent_extra_args is not None else []
        params = dict(self.params) if self.params is not None else {}
        create_dirs = list(self.create_dirs) if self.create_dirs is not None else []
        constraints = list(self.constraints) if self.constraints is not None else []
        acceptance_criteria = list(self.acceptance_criteria) if self.acceptance_criteria is not None else []
        return {
            "task_id": self.task_id,
            "project_name": self.project_name,
            "feature": self.feature,
            "agent_cmd": self.agent_cmd,
            "agent": {
                "provider": self.agent or "codex",
                "model": self.agent_model,
                "extra_args": list(extra_args),
            },
            "agent_model": self.agent_model,
            "agent_extra_args": extra_args,
            "agent_non_interactive": self.agent_non_interactive,
            "repo": self.repo,
            "base_dir": str(self.base_dir),
            "from_branch": self.from_branch,
            "session": self.session,
            "ticket": self.ticket,
            "task_doc": str(self.task_doc) if self.task_doc else None,
            "requirements": self.requirements,
            "constraints": constraints,
            "acceptance_criteria": acceptance_criteria,
            "params": params,
            "create_dirs": create_dirs,
            "pr_title": self.pr_title,
            "pr_body": self.pr_body,
            "pr_base": self.pr_base,
            "branch_remote": self.branch_remote,
            "max_retry_cycles": self.max_retry_cycles,
            "timeout_minutes": self.timeout_minutes,
            "auto_cleanup": self.auto_cleanup,
            "keep_branch_on_cleanup": self.keep_branch_on_cleanup,
            "commit_message": self.commit_message,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, spec_dir: Path | None = None) -> TaskSpec:
        """Build a validated ``TaskSpec`` from untyped JSON payload.

        Args:
            payload: Parsed JSON object from the spec file.
            spec_dir: Directory of the spec file, used to resolve relative
                paths (e.g. ``task_doc``). When ``None``, relative paths fall
                back to CWD resolution.
        """

        if not isinstance(payload, dict):
            raise AgvvError("Task spec root must be an object.")

        required = ["project_name", "feature", "repo"]
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise AgvvError(f"Task spec missing required fields: {', '.join(missing)}")

        task_id = _generate_task_id(str(payload["project_name"]), str(payload["feature"]))

        params = payload.get("params") or {}
        if not isinstance(params, dict):
            raise AgvvError("Task spec field 'params' must be an object.")

        create_dirs = payload.get("create_dirs") or []
        if not isinstance(create_dirs, list):
            raise AgvvError("Task spec field 'create_dirs' must be a list.")
        constraints = _coerce_string_list(payload.get("constraints"), "Task spec field 'constraints'")
        acceptance_criteria = _normalize_acceptance_criteria(payload.get("acceptance_criteria"))
        requirements = str(payload["requirements"]).strip() if payload.get("requirements") else None

        # Runtime agent selection is controlled by CLI flags (`task run --agent`).
        provider = "codex"
        model = None
        extra_args: list[str] = _coerce_agent_extra_args(payload.get("agent_extra_args"), "Task spec field 'agent_extra_args'")
        agent_cmd = build_agent_command(provider=provider, model=model, extra_args=extra_args)

        task_doc = _coerce_task_doc_path(payload.get("task_doc"), spec_dir=spec_dir)
        return cls(
            task_id=task_id,
            project_name=str(payload["project_name"]),
            feature=str(payload["feature"]),
            agent_cmd=agent_cmd,
            repo=str(payload["repo"]),
            base_dir=Path(str(payload.get("base_dir") or Path.cwd())).expanduser().resolve(),
            from_branch="main",
            session=(str(payload["session"]) if payload.get("session") else None),
            agent=provider,
            agent_model=model,
            agent_extra_args=extra_args,
            agent_non_interactive=_coerce_bool(payload.get("agent_non_interactive"), default=True),
            ticket=(str(payload["ticket"]) if payload.get("ticket") else None),
            task_doc=task_doc,
            requirements=requirements,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            params={str(k): str(v) for k, v in params.items()},
            create_dirs=[str(item) for item in create_dirs],
            pr_title=(str(payload["pr_title"]) if payload.get("pr_title") else None),
            pr_body=(str(payload["pr_body"]) if payload.get("pr_body") else None),
            pr_base=str(payload.get("pr_base", payload.get("from_branch", "main"))),
            branch_remote=str(payload.get("branch_remote", "origin")),
            max_retry_cycles=_coerce_int(payload.get("max_retry_cycles"), "max_retry_cycles", 5, min_value=0),
            timeout_minutes=_coerce_int(payload.get("timeout_minutes"), "timeout_minutes", 240, min_value=1),
            auto_cleanup=_coerce_bool(payload.get("auto_cleanup"), default=True),
            keep_branch_on_cleanup=_coerce_bool(payload.get("keep_branch_on_cleanup"), default=False),
            commit_message=(str(payload["commit_message"]) if payload.get("commit_message") else None),
        )
