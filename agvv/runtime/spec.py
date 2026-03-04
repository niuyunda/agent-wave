"""Task specification loading utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agvv.shared.errors import AgvvError
from agvv.runtime.models import TaskSpec

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_layout_name(value: Any, *, label: str) -> None:
    """Validate project/feature names before task creation."""

    if not isinstance(value, str) or not value.strip():
        raise AgvvError(f"Task spec field '{label}' must be a non-empty string.")
    normalized = value.strip()
    if "/" in normalized or "\\" in normalized:
        raise AgvvError(f"Task spec field '{label}' must not contain path separators.")
    if _SAFE_NAME_RE.fullmatch(normalized) is None:
        raise AgvvError(
            f"Task spec field '{label}' contains invalid characters. Use only letters, numbers, hyphens, and underscores."
        )
    if label == "feature" and normalized in {"main", "repo.git"}:
        raise AgvvError(f"Task spec field '{label}' value '{normalized}' is reserved.")


def _validate_task_doc_policy(payload: dict[str, Any]) -> None:
    """Enforce task_doc presence and Markdown format at spec-load boundary."""

    task_doc = payload.get("task_doc")
    if not isinstance(task_doc, str) or not task_doc.strip():
        raise AgvvError("Task spec field 'task_doc' is required and must be a Markdown (.md) file path.")
    if not task_doc.strip().lower().endswith(".md"):
        raise AgvvError("Task spec field 'task_doc' must be a Markdown file path ending with '.md'.")


def _validate_identity_fields(payload: dict[str, Any]) -> None:
    """Validate early identity fields to prevent late launch failures."""

    _validate_layout_name(payload.get("project_name"), label="project_name")
    _validate_layout_name(payload.get("feature"), label="feature")


def load_task_spec(path: Path) -> TaskSpec:
    """Load task spec from JSON."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgvvError(f"Failed to read spec file at {path}: {exc}") from exc

    payload: Any
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgvvError("Spec file is not valid JSON.") from exc

    if not isinstance(payload, dict):
        raise AgvvError("Task spec must be an object.")
    _validate_identity_fields(payload)
    _validate_task_doc_policy(payload)
    return TaskSpec.from_payload(payload, spec_dir=path.parent)
