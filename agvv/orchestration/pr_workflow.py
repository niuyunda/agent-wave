"""Pull-request orchestration helpers for gh-based workflows."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from agvv.orchestration.executor import CommandRunner, run_checked
from agvv.orchestration.models import PrCheckResult, PrFeedbackSummary, PrNextAction, PrWaitResult
from agvv.orchestration.pr_core import (
    check_pr_status as _check_pr_status_impl,
    recommend_pr_next_action as _recommend_pr_next_action_impl,
    summarize_pr_feedback as _summarize_pr_feedback_impl,
)
from agvv.shared.pr import PrStatus
from agvv.shared.errors import AgvvError

_PR_URL_RE = re.compile(r"/pull/([0-9]+)")
_run: CommandRunner = run_checked


def ensure_pr_number_for_branch(
    *,
    repo: str,
    feature: str,
    pr_base: str,
    title: str,
    body: str,
    worktree: Path,
    pr_number: int | None = None,
    run_cmd: CommandRunner | None = None,
) -> int:
    """Create or discover open PR number for a branch."""

    if pr_number is not None:
        return pr_number

    runner = run_cmd or _run
    create_error: AgvvError | None = None
    list_error: AgvvError | None = None

    try:
        create = runner(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--head",
                feature,
                "--base",
                pr_base,
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=worktree,
        )
        match = _PR_URL_RE.search(create.stdout.strip())
        if match:
            return int(match.group(1))
    except AgvvError as exc:
        create_error = exc

    listed = ""
    try:
        listed = runner(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                feature,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number",
            ],
            cwd=worktree,
        ).stdout.strip()
    except AgvvError as exc:
        list_error = exc

    if listed:
        return int(listed)
    if create_error is not None and list_error is not None:
        raise AgvvError(
            "Failed to resolve PR number: create failed and fallback lookup failed.\n"
            f"create_error={create_error}\n"
            f"list_error={list_error}"
        ) from list_error
    if create_error is not None:
        raise AgvvError(
            "Failed to resolve PR number: create failed and no existing open PR found.\n"
            f"create_error={create_error}"
        ) from create_error
    if list_error is not None:
        raise AgvvError(f"Failed to resolve PR number from gh list: {list_error}") from list_error
    raise AgvvError("Failed to resolve PR number after creation.")


def check_pr_status(repo: str, pr_number: int, *, run_cmd: CommandRunner | None = None) -> PrCheckResult:
    """Check PR state via gh and map to minimal status for fast review loops."""

    runner = run_cmd or _run
    return _check_pr_status_impl(repo=repo, pr_number=pr_number, run_cmd=runner)


def wait_pr_status(
    repo: str,
    pr_number: int,
    interval_seconds: int = 120,
    max_attempts: int = 30,
    *,
    run_cmd: CommandRunner | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> PrWaitResult:
    """Poll PR status every interval until terminal or attempts exhausted."""

    if interval_seconds <= 0:
        raise AgvvError("interval_seconds must be > 0")
    if max_attempts <= 0:
        raise AgvvError("max_attempts must be > 0")

    sleeper = sleep_fn or time.sleep
    if run_cmd is None:
        last = check_pr_status(repo=repo, pr_number=pr_number)
    else:
        last = check_pr_status(repo=repo, pr_number=pr_number, run_cmd=run_cmd)
    terminal = {PrStatus.DONE, PrStatus.CLOSED, PrStatus.NEEDS_WORK}
    attempts = 1

    while last.status not in terminal and attempts < max_attempts:
        sleeper(interval_seconds)
        if run_cmd is None:
            last = check_pr_status(repo=repo, pr_number=pr_number)
        else:
            last = check_pr_status(repo=repo, pr_number=pr_number, run_cmd=run_cmd)
        attempts += 1

    return PrWaitResult(result=last, attempts=attempts, timed_out=last.status == PrStatus.WAITING)


def recommend_pr_next_action(repo: str, pr_number: int, *, run_cmd: CommandRunner | None = None) -> PrNextAction:
    """Return a minimal next-step recommendation for a PR."""

    if run_cmd is None:
        result = check_pr_status(repo=repo, pr_number=pr_number)
    else:
        result = check_pr_status(repo=repo, pr_number=pr_number, run_cmd=run_cmd)
    return _recommend_pr_next_action_impl(result)


def summarize_pr_feedback(repo: str, pr_number: int, *, run_cmd: CommandRunner | None = None) -> PrFeedbackSummary:
    """Summarize PR comments/reviews into actionable items and skipped reasons."""

    runner = run_cmd or _run
    return _summarize_pr_feedback_impl(repo=repo, pr_number=pr_number, run_cmd=runner)


def write_pr_feedback_file(
    *,
    worktree: Path,
    task_id: str,
    pr_number: int,
    feedback: PrFeedbackSummary,
) -> Path:
    """Persist feedback summary into the feature worktree and return file path."""

    feedback_path = worktree / ".agvv" / "feedback.txt"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"PR feedback cycle for task={task_id} pr={pr_number}",
        "",
        "Actionable:",
        *[f"- {item}" for item in feedback.actionable],
        "",
        "Skipped:",
        *[f"- {item}" for item in feedback.skipped[:10]],
    ]
    feedback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return feedback_path
