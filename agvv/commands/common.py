"""Shared CLI command utilities."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from agvv.shared.errors import AgvvError
from agvv.runtime.models import TaskState


def exit_with_agvv_error(exc: AgvvError) -> NoReturn:
    """Render operational errors to stderr and exit non-zero."""

    typer.secho(str(exc), err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1) from exc


def resolve_optional_path(path: str | None) -> Path | None:
    """Resolve an optional path string to an absolute ``Path``."""

    return Path(path).expanduser().resolve() if path else None


def parse_task_state(value: str | None) -> TaskState | None:
    """Parse optional task state value."""

    if value is None:
        return None
    try:
        return TaskState(value)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TaskState)
        raise typer.BadParameter(f"Unsupported --state value '{value}'. Use one of: {supported}") from exc
