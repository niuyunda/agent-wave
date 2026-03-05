"""PR status and feedback parsing helpers."""

from __future__ import annotations

import json

from agvv.orchestration.executor import CommandRunner
from agvv.orchestration.models import PrCheckResult, PrFeedbackSummary, PrNextAction
from agvv.shared.pr import PrStatus
from agvv.shared.errors import AgvvError


def check_pr_status(
    repo: str,
    pr_number: int,
    *,
    run_cmd: CommandRunner,
) -> PrCheckResult:
    """Check PR state and map to minimal status for review loops."""

    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "state,mergedAt,reviewDecision,statusCheckRollup",
    ]
    try:
        payload = json.loads(run_cmd(cmd).stdout)
    except json.JSONDecodeError as exc:
        raise AgvvError(
            f"Invalid JSON from gh pr view for {repo}#{pr_number}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AgvvError(
            f"Invalid gh pr view payload for {repo}#{pr_number}: expected object, got {type(payload).__name__}: {payload!r}"
        )

    state = str(payload.get("state", ""))
    merged_at = payload.get("mergedAt")
    review_decision = payload.get("reviewDecision")

    if merged_at:
        return PrCheckResult(
            status=PrStatus.DONE,
            reason="merged",
            state=state,
            review_decision=review_decision,
        )

    if state != "OPEN":
        return PrCheckResult(
            status=PrStatus.CLOSED,
            reason="not_open",
            state=state,
            review_decision=review_decision,
        )

    if review_decision == "CHANGES_REQUESTED":
        return PrCheckResult(
            status=PrStatus.NEEDS_WORK,
            reason="changes_requested",
            state=state,
            review_decision=review_decision,
        )

    checks = payload.get("statusCheckRollup") or []
    failing = {
        "FAILURE",
        "TIMED_OUT",
        "CANCELLED",
        "ACTION_REQUIRED",
        "STARTUP_FAILURE",
    }
    failing_state = {"FAILURE", "FAILED", "ERROR"}
    for check in checks:
        entry = check or {}
        conclusion = str(entry.get("conclusion") or "").upper()
        state_value = str(entry.get("state") or entry.get("status") or "").upper()
        if conclusion in failing:
            return PrCheckResult(
                status=PrStatus.NEEDS_WORK,
                reason=f"ci_{conclusion.lower()}",
                state=state,
                review_decision=review_decision,
            )
        if state_value in failing_state:
            return PrCheckResult(
                status=PrStatus.NEEDS_WORK,
                reason=f"ci_{state_value.lower()}",
                state=state,
                review_decision=review_decision,
            )

    return PrCheckResult(
        status=PrStatus.WAITING,
        reason="pending_review_or_ci",
        state=state,
        review_decision=review_decision,
    )


def recommend_pr_next_action(result: PrCheckResult) -> PrNextAction:
    """Return a minimal next-step recommendation from a PR check result."""

    if result.status == PrStatus.NEEDS_WORK:
        return PrNextAction(
            status=result.status,
            action="retry",
            note="Run fix workflow, push updates, then reconcile with `agvv daemon run --once`.",
        )
    if result.status == PrStatus.DONE:
        return PrNextAction(
            status=result.status,
            action="cleanup",
            note="PR merged; run feature cleanup.",
        )
    if result.status == PrStatus.CLOSED:
        return PrNextAction(
            status=result.status,
            action="stop",
            note="PR closed without merge; manual follow-up needed.",
        )
    return PrNextAction(
        status=result.status,
        action="wait",
        note="Keep polling via daemon (`agvv daemon run --once` or loop mode).",
    )


def summarize_pr_feedback(
    repo: str,
    pr_number: int,
    *,
    run_cmd: CommandRunner,
) -> PrFeedbackSummary:
    """Summarize PR comments/reviews into actionable items and skipped reasons."""

    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "comments,reviews",
    ]
    try:
        payload = json.loads(run_cmd(cmd).stdout)
    except json.JSONDecodeError as exc:
        raise AgvvError(
            f"Invalid JSON from gh pr comments for {repo}#{pr_number}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AgvvError(
            f"Invalid gh pr comments payload for {repo}#{pr_number}: expected object, got {type(payload).__name__}: {payload!r}"
        )

    actionable: list[str] = []
    skipped: list[str] = []

    for comment in payload.get("comments", []) or []:
        body = str(comment.get("body") or "").strip()
        if not body:
            continue
        lower = body.lower()
        if "review in progress" in lower or "walkthrough" in lower:
            skipped.append("Skipped informational bot comment")
            continue
        if "actionable comments posted" in lower or "potential issue" in lower:
            actionable.append(body.splitlines()[0][:180])
        else:
            skipped.append("Skipped non-actionable comment")

    for review in payload.get("reviews", []) or []:
        body = str(review.get("body") or "").strip()
        if not body:
            continue
        lower = body.lower()
        if "actionable comments posted" in lower or "potential issue" in lower:
            actionable.append(body.splitlines()[0][:180])

    return PrFeedbackSummary(actionable=tuple(actionable), skipped=tuple(skipped))
