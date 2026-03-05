"""PR-driven state handlers for coding completion and feedback loops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from agvv.runtime.adapters import DEFAULT_ORCHESTRATION_PORT as port
from agvv.runtime.models import TaskState
from agvv.runtime.prompting import (
    detect_blocking_prompt,
    validate_dod_result,
    write_output_summary,
)
from agvv.runtime.session_lifecycle import start_tmux_agent
from agvv.runtime.store import TaskSnapshot, TaskStore, now_iso, parse_iso
from agvv.runtime.task_helpers import feature_worktree_path, mark_failed, task_doc_text
from agvv.shared.pr import PrStatus

CleanupTaskFn = Callable[[str, Path | None, bool], TaskSnapshot]


def _coding_session_timed_out(task: TaskSnapshot) -> bool:
    """Return whether coding session runtime exceeded configured timeout."""

    since = parse_iso(task.started_at or task.created_at)
    elapsed = datetime.now(tz=timezone.utc) - since
    return elapsed > timedelta(minutes=task.spec.timeout_minutes)


def handle_coding_completion(
    store: TaskStore,
    task: TaskSnapshot,
) -> TaskSnapshot:
    """Move ``CODING`` task to ``PR_OPEN`` when coding session is done."""

    worktree = feature_worktree_path(task)

    if port.tmux_session_exists(task.session):
        blocked_detection = detect_blocking_prompt(worktree=worktree)
        if blocked_detection is not None:
            reason_code, reason_label = blocked_detection
            message = (
                "Coding session appears blocked by interactive prompt "
                f"({reason_label}). Retry with forced session restart after fixing agent configuration."
            )
            store.add_event(
                task.id,
                "error",
                "coding.blocked",
                message,
                {
                    "session": task.session,
                    "reason_code": reason_code,
                    "reason": reason_label,
                },
            )
            return store.update_task(
                task.id,
                state=TaskState.BLOCKED,
                last_error=message,
                finished_at=now_iso(),
            )
        if _coding_session_timed_out(task):
            message = f"Coding session exceeded timeout ({task.spec.timeout_minutes} minutes)."
            store.add_event(
                task.id,
                "error",
                "coding.timeout",
                message,
                {"session": task.session, "timeout_minutes": task.spec.timeout_minutes},
            )
            try:
                port.tmux_kill_session(task.session)
            except Exception as exc:
                store.add_event(
                    task.id,
                    "warning",
                    "coding.timeout.kill_session",
                    f"Failed to terminate timed-out tmux session: {exc}",
                    {"session": task.session},
                )
            return store.update_task(
                task.id,
                state=TaskState.TIMED_OUT,
                last_error="coding_timeout",
                finished_at=now_iso(),
            )
        return task

    if not worktree.exists():
        return mark_failed(
            store, task, "coding.verify", f"Worktree missing: {worktree}"
        )
    summary_path = write_output_summary(worktree=worktree)
    if summary_path is not None:
        store.add_event(
            task.id,
            "info",
            "coding.output.summary",
            "Captured agent output summary",
            {"summary_path": str(summary_path)},
        )
    dod_ok, dod_message = validate_dod_result(worktree=worktree, spec=task.spec)
    if not dod_ok:
        return mark_failed(
            store, task, "coding.dod", f"DoD validation failed: {dod_message}"
        )
    store.add_event(
        task.id, "info", "coding.dod", "DoD validation passed", {"details": dod_message}
    )

    try:
        port.commit_and_push_branch(
            worktree=worktree,
            feature=task.feature,
            base_branch=task.spec.pr_base,
            remote=task.spec.branch_remote,
            commit_message=task.spec.commit_message
            or f"feat({task.feature}): implement {task.id}",
        )
        pr_number = port.ensure_pr_number_for_branch(
            repo=task.repo,
            feature=task.feature,
            pr_base=task.spec.pr_base,
            title=task.spec.pr_title or f"[agvv] {task.feature}",
            body=task_doc_text(task.spec),
            worktree=worktree,
            pr_number=task.pr_number,
        )
    except Exception as exc:
        return mark_failed(
            store, task, "coding.finalize", f"Finalize coding failed: {exc}"
        )

    store.add_event(
        task.id, "info", "pr.open", "PR opened/confirmed", {"pr_number": pr_number}
    )
    return store.update_task(
        task.id, state=TaskState.PR_OPEN, pr_number=pr_number, last_error=None
    )


def handle_pr_cycle(
    store: TaskStore,
    task: TaskSnapshot,
    cleanup_task_fn: CleanupTaskFn,
) -> TaskSnapshot:
    """Advance ``PR_OPEN`` task through review/merge/close/retry states."""

    if task.pr_number is None:
        return mark_failed(store, task, "pr.check", "PR number missing for PR cycle.")

    elapsed = datetime.now(tz=timezone.utc) - parse_iso(task.created_at)
    if elapsed > timedelta(minutes=task.spec.timeout_minutes):
        timed = store.update_task(
            task.id,
            state=TaskState.TIMED_OUT,
            finished_at=now_iso(),
            last_error="task_timeout",
        )
        store.add_event(
            task.id,
            "error",
            "task.timeout",
            "Task timed out",
            {"timeout_minutes": task.spec.timeout_minutes},
        )
        if task.spec.auto_cleanup:
            return cleanup_task_fn(task.id, store.path, False)
        return timed

    try:
        result = port.check_pr_status(task.repo, task.pr_number)
    except Exception as exc:
        return mark_failed(store, task, "pr.check", f"PR status check failed: {exc}")

    if result.status == PrStatus.WAITING:
        return store.update_task(task.id, state=TaskState.PR_OPEN)

    if result.status == PrStatus.DONE:
        merged = store.update_task(
            task.id, state=TaskState.PR_MERGED, finished_at=now_iso(), last_error=None
        )
        store.add_event(task.id, "info", "pr.merged", "PR merged")
        if task.spec.auto_cleanup:
            return cleanup_task_fn(task.id, store.path, False)
        return merged

    if result.status == PrStatus.CLOSED:
        closed = store.update_task(
            task.id, state=TaskState.PR_CLOSED, finished_at=now_iso(), last_error=None
        )
        store.add_event(task.id, "info", "pr.closed", "PR closed")
        if task.spec.auto_cleanup:
            return cleanup_task_fn(task.id, store.path, False)
        return closed

    try:
        feedback = port.summarize_pr_feedback(task.repo, task.pr_number)
    except Exception as exc:
        return mark_failed(
            store,
            task,
            "pr.feedback.fetch",
            f"Failed to summarize PR feedback for {task.repo}#{task.pr_number}: {exc}",
        )
    if task.repair_cycles >= task.spec.max_retry_cycles:
        return mark_failed(
            store,
            task,
            "pr.retry",
            f"Reached max retry cycles ({task.spec.max_retry_cycles}). Actionable comments: {len(feedback.actionable)}",
        )

    worktree = feature_worktree_path(task)
    if not worktree.exists():
        return mark_failed(store, task, "pr.retry", f"Worktree missing: {worktree}")

    try:
        feedback_path = port.write_pr_feedback_file(
            worktree=worktree,
            task_id=task.id,
            pr_number=task.pr_number,
            feedback=feedback,
        )
    except Exception as exc:
        return mark_failed(
            store,
            task,
            "pr.feedback.write",
            (
                f"Failed to write PR feedback file for {task.repo}#{task.pr_number} "
                f"at worktree={worktree}: {exc}"
            ),
        )

    if port.tmux_session_exists(task.session):
        return store.update_task(task.id, state=TaskState.CODING)

    try:
        artifacts = start_tmux_agent(
            store, task, worktree, event_step_prefix="pr.retry"
        )
    except Exception as exc:
        return mark_failed(
            store, task, "pr.retry", f"Failed to relaunch coding session: {exc}"
        )

    store.add_event(
        task.id,
        "info",
        "pr.retry",
        "Feedback received; coding session relaunched",
        {
            "cycle": task.repair_cycles + 1,
            "feedback_file": str(feedback_path),
            "prompt_path": str(artifacts["prompt_path"]),
            "input_snapshot_path": str(artifacts["input_snapshot_path"]),
            "output_log_path": str(artifacts["output_log_path"]),
        },
    )
    return store.update_task(
        task.id,
        state=TaskState.CODING,
        repair_cycles=task.repair_cycles + 1,
        last_error=None,
    )
