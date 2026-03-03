"""Task specification loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agvv.shared.errors import AgvvError
from agvv.runtime.models import TaskSpec


def load_task_spec(path: Path) -> TaskSpec:
    """Load task spec from JSON or YAML (if PyYAML is installed)."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgvvError(f"Failed to read spec file at {path}: {exc}") from exc

    payload: Any
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AgvvError(
                "Spec file is not valid JSON. Install PyYAML to use YAML spec files."
            ) from exc
        payload = yaml.safe_load(raw)

    if not isinstance(payload, dict):
        raise AgvvError("Task spec must be an object.")
    return TaskSpec.from_payload(payload)
