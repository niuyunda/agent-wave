"""Task state and specification models."""

from __future__ import annotations

import shlex
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationError

from agvv.shared.errors import AgvvError

_AGENT_PROVIDER_ALIASES = {
    "codex": "codex",
    "claude": "claude_code",
    "claude_code": "claude_code",
    "claude-code": "claude_code",
}


def _generate_task_id(project_name: str, feature: str) -> str:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{project_name}-{feature}-{stamp}"


class TaskState(str, Enum):
    """Lifecycle states for the task state machine."""
    PENDING   = "pending"    # created, not yet launched
    RUNNING   = "running"    # tmux session active
    DONE      = "done"       # agent session ended cleanly
    FAILED    = "failed"     # error during setup or launch
    TIMED_OUT = "timed_out"  # session exceeded timeout
    CLEANED   = "cleaned"    # worktree removed


TERMINAL_STATES = {TaskState.DONE, TaskState.TIMED_OUT, TaskState.FAILED, TaskState.CLEANED}
ACTIVE_STATES = {TaskState.PENDING, TaskState.RUNNING}
RECOVERABLE_RETRY_STATES = {TaskState.FAILED, TaskState.TIMED_OUT, TaskState.RUNNING}


def normalize_agent_provider(value: str | None) -> str:
    """Normalize provider aliases into canonical provider identifiers."""
    raw = (value or "codex").strip() or "codex"
    key = raw.lower().replace("-", "_")
    provider = _AGENT_PROVIDER_ALIASES.get(key)
    if provider is None:
        supported = ", ".join(sorted(set(_AGENT_PROVIDER_ALIASES.values())))
        raise AgvvError(f"Unsupported agent provider '{raw}'. Supported: {supported}.")
    return provider


def build_agent_command(provider: str, model: str | None, extra_args: list[str]) -> str:
    """Build a shell-safe command line for the configured coding agent."""
    if provider == "codex":
        parts = ["codex"]
    elif provider == "claude_code":
        parts = ["claude"]
    else:
        raise AgvvError(f"Unsupported agent provider '{provider}'.")
    if model:
        parts.extend(["--model", model])
    parts.extend(extra_args)
    return shlex.join(parts)


class TaskSpec(BaseModel):
    """Task spec consumed by the state machine."""
    model_config = ConfigDict(frozen=True, validate_default=True, arbitrary_types_allowed=True)

    project_name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    feature: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    repo: str | None = None          # optional GitHub owner/repo slug for the agent's use
    base_dir: Path = Field(default_factory=Path.cwd)
    from_branch: str = "main"
    session: str | None = None
    agent: str | None = "codex"
    agent_model: str | None = None
    agent_extra_args: list[str] = Field(default_factory=list)
    agent_non_interactive: bool = True
    ticket: str | None = None
    task_doc: Path | None = None
    requirements: str | None = None
    constraints: list[str] = Field(default_factory=list)
    timeout_minutes: int = Field(default=240, ge=1)

    # computed at validation time
    task_id: str = ""
    agent_cmd: str = ""
    spec_dir__: Path | None = Field(default=None, exclude=True)

    @field_validator("project_name", "feature", mode="before")
    @classmethod
    def check_non_empty(cls, v: Any) -> str:
        if v is None or str(v).strip() == "":
            raise ValueError("Must be a non-empty string")
        v_str = str(v).strip()
        if v_str in ("main", "repo.git"):
            raise ValueError(f"Value '{v_str}' is reserved.")
        return v_str

    @field_validator("constraints", "agent_extra_args", mode="before")
    @classmethod
    def sanitize_string_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("Must be a list")
        parsed = []
        for item in v:
            item_str = str(item).strip() if item is not None else ""
            if not item_str:
                raise ValueError("Must contain only non-empty strings")
            parsed.append(item_str)
        return parsed

    @model_validator(mode="before")
    @classmethod
    def prepare_data(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Task spec must be an object.")

        task_doc = data.get("task_doc")
        if task_doc is not None:
            if not isinstance(task_doc, str) or not task_doc.strip().lower().endswith(".md"):
                raise ValueError("task_doc must be a Markdown (.md) file path")
            p = Path(task_doc.strip()).expanduser()
            spec_dir = data.get("spec_dir__")
            if not p.is_absolute() and spec_dir:
                p = (spec_dir / p).resolve()
            else:
                p = p.resolve()
            data["task_doc"] = p

        if "base_dir" in data and data["base_dir"]:
            data["base_dir"] = Path(str(data["base_dir"])).expanduser().resolve()

        return data

    @model_validator(mode="after")
    def compute_fields(self) -> TaskSpec:
        agent_provider = normalize_agent_provider(self.agent)
        object.__setattr__(self, "agent", agent_provider)
        if not self.task_id:
            object.__setattr__(self, "task_id", _generate_task_id(self.project_name, self.feature))
        if not self.agent_cmd:
            cmd = build_agent_command(agent_provider, self.agent_model, self.agent_extra_args)
            object.__setattr__(self, "agent_cmd", cmd)
        return self

    def normalized_session(self) -> str:
        """Return a deterministic tmux session name for the task."""
        return self.session or f"agvv-{self.task_id}"

    def to_payload(self) -> dict[str, Any]:
        """Serialize spec into JSON-safe primitives."""
        return {
            "task_id": self.task_id,
            "project_name": self.project_name,
            "feature": self.feature,
            "agent_cmd": self.agent_cmd,
            "agent": self.agent or "codex",
            "agent_model": self.agent_model,
            "agent_extra_args": list(self.agent_extra_args),
            "agent_non_interactive": self.agent_non_interactive,
            "repo": self.repo,
            "base_dir": str(self.base_dir),
            "from_branch": self.from_branch,
            "session": self.session,
            "ticket": self.ticket,
            "task_doc": str(self.task_doc) if self.task_doc else None,
            "requirements": self.requirements,
            "constraints": list(self.constraints),
            "timeout_minutes": self.timeout_minutes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, spec_dir: Path | None = None) -> TaskSpec:
        """Build a validated TaskSpec from a user-authored spec JSON file."""
        if not isinstance(payload, dict):
            raise AgvvError("Task spec root must be an object.")
        payload = payload.copy()
        if spec_dir:
            payload["spec_dir__"] = spec_dir

        # Reset runtime-controlled fields so spec files cannot lock them in.
        payload["agent"] = "codex"
        payload["agent_model"] = None
        payload.pop("task_id", None)
        payload.pop("agent_cmd", None)
        if not payload.get("from_branch"):
            payload["from_branch"] = "main"

        has_task_doc = bool(payload.get("task_doc"))
        has_requirements = bool((payload.get("requirements") or "").strip())
        if not has_task_doc and not has_requirements:
            raise AgvvError("Spec must include 'task_doc' (a Markdown file) or 'requirements' (a string).")

        try:
            return cls.model_validate(payload)
        except ValidationError as e:
            raise AgvvError(f"Validation error: {e}") from e

    @classmethod
    def from_db_payload(cls, payload: dict[str, Any]) -> TaskSpec:
        """Reconstruct a TaskSpec from a stored DB spec_json payload."""
        if not isinstance(payload, dict):
            raise AgvvError("Task spec root must be an object.")
        payload = payload.copy()

        # Handle old nested agent dict written by previous to_payload() format.
        agent_val = payload.get("agent")
        if isinstance(agent_val, dict):
            payload["agent"] = agent_val.get("provider", "codex")
            if not payload.get("agent_model"):
                payload["agent_model"] = agent_val.get("model")
            if not payload.get("agent_extra_args"):
                payload["agent_extra_args"] = agent_val.get("extra_args", [])

        payload.pop("agent_cmd", None)

        try:
            return cls.model_validate(payload)
        except ValidationError as e:
            raise AgvvError(f"Validation error: {e}") from e
