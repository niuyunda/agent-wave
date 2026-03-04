"""Task command handlers extracted from CLI presentation wiring."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from agvv.commands.contracts import CleanupTaskFn, ListTaskStatusesFn, RetryTaskFn, RunTaskFromSpecFn
from agvv.runtime.models import TaskState


def execute_task_run(
    *,
    spec: str,
    db_path: str | None,
    agent: str | None,
    model: str | None,
    project_dir: str | None,
    run_task_from_spec: RunTaskFromSpecFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Run task creation/start flow and return one output line."""

    task = run_task_from_spec(
        spec_path=Path(spec).expanduser().resolve(),
        db_path=resolve_optional_path(db_path),
        agent_provider=agent,
        agent_model=model,
        project_dir=resolve_optional_path(project_dir),
    )
    return (
        f"Task started: {task.id}\tstate={task.state.value}\t"
        f"target={task.project_name}/{task.feature}\tsession={task.session}"
    )


def execute_task_status(
    *,
    db_path: str | None,
    task_id: str | None,
    state: str | None,
    list_task_statuses: ListTaskStatusesFn,
    resolve_optional_path: Callable[[str | None], Path | None],
    parse_task_state: Callable[[str | None], TaskState | None],
) -> list[str]:
    """Query task status and return rendered output lines."""

    parsed_state = parse_task_state(state)
    tasks = list_task_statuses(db_path=resolve_optional_path(db_path), state=parsed_state)

    if task_id is not None:
        tasks = [item for item in tasks if item.id == task_id]

    if not tasks:
        return ["No tasks found."]

    lines: list[str] = []
    for task in tasks:
        pr_value = str(task.pr_number) if task.pr_number is not None else "-"
        if task.last_error is None:
            error_value = "-"
        else:
            normalized_error = re.sub(r"[\r\n\t]+", " ", task.last_error)
            error_value = re.sub(r"\s+", " ", normalized_error).strip() or "-"
        lines.append(
            f"{task.id}\t{task.state.value}\t{task.project_name}/{task.feature}\t"
            f"session={task.session}\tpr={pr_value}\tcycles={task.repair_cycles}\t"
            f"error={error_value}\tupdated={task.updated_at}"
        )
    return lines


def execute_task_retry(
    *,
    task_id: str,
    db_path: str | None,
    session: str | None,
    retry_task: RetryTaskFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Retry one task and return one output line."""

    task = retry_task(task_id=task_id, db_path=resolve_optional_path(db_path), session=session)
    return f"Task retried: {task.id}\tstate={task.state.value}\tsession={task.session}"


def execute_task_cleanup(
    *,
    task_id: str,
    db_path: str | None,
    force: bool,
    cleanup_task: CleanupTaskFn,
    resolve_optional_path: Callable[[str | None], Path | None],
) -> str:
    """Cleanup one task and return one output line."""

    task = cleanup_task(task_id=task_id, db_path=resolve_optional_path(db_path), force=force)
    return f"Task cleaned: {task.id}\tstate={task.state.value}"
