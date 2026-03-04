from __future__ import annotations

import json
from pathlib import Path

import pytest

from agvv.orchestration import (
    AgvvError,
    check_pr_status,
    commit_and_push_branch,
    ensure_pr_number_for_branch,
    git_remote_exists,
    recommend_pr_next_action,
    summarize_pr_feedback,
    wait_pr_status,
    write_pr_feedback_file,
)
from agvv.orchestration.models import PrFeedbackSummary
from agvv.shared.pr import PrStatus


def test_commit_and_push_branch_commits_when_worktree_dirty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run_git(args: list[str], cwd: Path | None = None):
        calls.append(args)
        if args[:2] == ["remote", "get-url"]:
            return type("R", (), {"stdout": "git@example.com:owner/repo.git\n"})()
        if args == ["status", "--porcelain"]:
            return type("R", (), {"stdout": " M README.md\n"})()
        if args[:2] == ["rev-list", "--count"]:
            return type("R", (), {"stdout": "2\n"})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    commit_and_push_branch(
        worktree=tmp_path,
        feature="feat-1",
        base_branch="main",
        remote="origin",
        commit_message="feat: update readme",
    )
    assert ["add", "-A", "--", ".", ":(exclude).agvv/**"] in calls
    assert ["commit", "-m", "feat: update readme"] in calls
    assert ["push", "-u", "origin", "feat-1"] in calls


def test_commit_and_push_branch_fails_when_not_ahead(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_run_git(args: list[str], cwd: Path | None = None):
        if args[:2] == ["remote", "get-url"]:
            return type("R", (), {"stdout": "git@example.com:owner/repo.git\n"})()
        if args == ["status", "--porcelain"]:
            return type("R", (), {"stdout": ""})()
        if args[:2] == ["rev-list", "--count"]:
            return type("R", (), {"stdout": "0\n"})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    with pytest.raises(AgvvError, match="produced no commits ahead of base branch"):
        commit_and_push_branch(
            worktree=tmp_path,
            feature="feat-1",
            base_branch="main",
            remote="origin",
            commit_message="feat: update readme",
        )


def test_commit_and_push_branch_fails_when_remote_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run_git(args: list[str], cwd: Path | None = None):
        calls.append(args)
        if args[:2] == ["remote", "get-url"]:
            raise AgvvError("Command failed: git remote get-url origin")
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    with pytest.raises(AgvvError, match="No git remote 'origin' configured"):
        commit_and_push_branch(
            worktree=tmp_path,
            feature="feat-1",
            base_branch="main",
            remote="origin",
            commit_message="feat: update readme",
        )
    assert calls == [["remote", "get-url", "origin"]]


def test_commit_and_push_branch_ignores_agvv_internal_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run_git(args: list[str], cwd: Path | None = None):
        calls.append(args)
        if args[:2] == ["remote", "get-url"]:
            return type("R", (), {"stdout": "git@example.com:owner/repo.git\n"})()
        if args == ["status", "--porcelain"]:
            return type("R", (), {"stdout": "?? .agvv/context.json\n M .agvv/feedback.txt\n"})()
        if args[:2] == ["rev-list", "--count"]:
            return type("R", (), {"stdout": "0\n"})()
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    with pytest.raises(AgvvError, match="produced no commits ahead of base branch"):
        commit_and_push_branch(
            worktree=tmp_path,
            feature="feat-1",
            base_branch="main",
            remote="origin",
            commit_message="feat: update readme",
        )
    assert ["add", "-A", "--", ".", ":(exclude).agvv/**"] not in calls
    assert ["commit", "-m", "feat: update readme"] not in calls
    assert ["push", "-u", "origin", "feat-1"] not in calls


def test_git_remote_exists_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_run_git(args: list[str], cwd: Path | None = None):
        assert args == ["remote", "get-url", "origin"]
        return type("R", (), {"stdout": "git@example.com:owner/repo.git\n"})()

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    assert git_remote_exists(worktree=tmp_path, remote="origin") is True


def test_git_remote_exists_false_when_lookup_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_run_git(args: list[str], cwd: Path | None = None):
        raise AgvvError("Command failed: git remote get-url origin")

    monkeypatch.setattr("agvv.orchestration.git_ops._run_git", _fake_run_git)
    assert git_remote_exists(worktree=tmp_path, remote="origin") is False


def test_ensure_pr_number_for_branch_falls_back_when_create_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fake_run(cmd: list[str], cwd: Path | None = None):
        if cmd[:4] == ["gh", "pr", "create", "--repo"]:
            raise AgvvError("Command failed: gh pr create ... already exists")
        if cmd[:4] == ["gh", "pr", "list", "--repo"]:
            return type("R", (), {"stdout": "123\n"})()
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    pr_number = ensure_pr_number_for_branch(
        repo="owner/repo",
        feature="feat-pr",
        pr_base="main",
        title="[agvv] feat-pr",
        body="Task body",
        worktree=tmp_path,
    )
    assert pr_number == 123


def test_ensure_pr_number_for_branch_raises_when_create_and_list_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_run(cmd: list[str], cwd: Path | None = None):
        if cmd[:4] == ["gh", "pr", "create", "--repo"]:
            raise AgvvError("create failed")
        if cmd[:4] == ["gh", "pr", "list", "--repo"]:
            raise AgvvError("list failed")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    with pytest.raises(AgvvError, match="create failed and fallback lookup failed"):
        ensure_pr_number_for_branch(
            repo="owner/repo",
            feature="feat-pr",
            pr_base="main",
            title="[agvv] feat-pr",
            body="Task body",
            worktree=tmp_path,
        )


def test_check_pr_status_maps_changes_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(_cmd, cwd=None):
        return type(
            "R",
            (),
            {
                "stdout": json.dumps(
                    {
                        "state": "OPEN",
                        "mergedAt": None,
                        "reviewDecision": "CHANGES_REQUESTED",
                        "statusCheckRollup": [],
                    }
                )
            },
        )()

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    result = check_pr_status("owner/repo", 1)
    assert result.status == PrStatus.NEEDS_WORK


def test_check_pr_status_maps_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(_cmd, cwd=None):
        return type(
            "R",
            (),
            {
                "stdout": json.dumps(
                    {
                        "state": "MERGED",
                        "mergedAt": "2026-01-01T00:00:00Z",
                        "reviewDecision": "APPROVED",
                        "statusCheckRollup": [],
                    }
                )
            },
        )()

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    result = check_pr_status("owner/repo", 1)
    assert result.status == PrStatus.DONE


def test_check_pr_status_maps_failed_state_without_conclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(_cmd, cwd=None):
        return type(
            "R",
            (),
            {
                "stdout": json.dumps(
                    {
                        "state": "OPEN",
                        "mergedAt": None,
                        "reviewDecision": None,
                        "statusCheckRollup": [{"state": "ERROR", "conclusion": None}],
                    }
                )
            },
        )()

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    result = check_pr_status("owner/repo", 1)
    assert result.status == PrStatus.NEEDS_WORK


def test_wait_pr_status_polls_until_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _fake_check(repo: str, pr_number: int):
        calls["n"] += 1
        if calls["n"] < 3:
            return type("R", (), {"status": PrStatus.WAITING, "reason": "pending", "state": "OPEN", "review_decision": None})()
        return type("R", (), {"status": PrStatus.NEEDS_WORK, "reason": "changes_requested", "state": "OPEN", "review_decision": "CHANGES_REQUESTED"})()

    monkeypatch.setattr("agvv.orchestration.pr_workflow.check_pr_status", _fake_check)
    monkeypatch.setattr("agvv.orchestration.pr_workflow.time.sleep", lambda _s: None)
    wait_result = wait_pr_status("owner/repo", 7, interval_seconds=1, max_attempts=5)
    assert wait_result.result.status == PrStatus.NEEDS_WORK
    assert wait_result.attempts == 3
    assert wait_result.timed_out is False


def test_wait_pr_status_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agvv.orchestration.pr_workflow.check_pr_status",
        lambda repo, pr_number: type("R", (), {"status": PrStatus.WAITING, "reason": "pending", "state": "OPEN", "review_decision": None})(),
    )
    monkeypatch.setattr("agvv.orchestration.pr_workflow.time.sleep", lambda _s: None)
    wait_result = wait_pr_status("owner/repo", 9, interval_seconds=1, max_attempts=3)
    assert wait_result.result.status == PrStatus.WAITING
    assert wait_result.attempts == 3
    assert wait_result.timed_out is True


def test_wait_pr_status_rejects_non_positive_interval() -> None:
    with pytest.raises(AgvvError, match="interval_seconds must be > 0"):
        wait_pr_status("owner/repo", 1, interval_seconds=0, max_attempts=1)


def test_wait_pr_status_rejects_non_positive_attempts() -> None:
    with pytest.raises(AgvvError, match="max_attempts must be > 0"):
        wait_pr_status("owner/repo", 1, interval_seconds=1, max_attempts=0)


def test_recommend_pr_next_action_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agvv.orchestration.pr_workflow.check_pr_status",
        lambda repo, pr_number: type("R", (), {"status": PrStatus.WAITING, "reason": "pending", "state": "OPEN", "review_decision": None})(),
    )
    rec = recommend_pr_next_action("owner/repo", 3)
    assert rec.action == "wait"


def test_recommend_pr_next_action_needs_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agvv.orchestration.pr_workflow.check_pr_status",
        lambda repo, pr_number: type("R", (), {"status": PrStatus.NEEDS_WORK, "reason": "changes_requested", "state": "OPEN", "review_decision": "CHANGES_REQUESTED"})(),
    )
    rec = recommend_pr_next_action("owner/repo", 3)
    assert rec.action == "retry"


def test_summarize_pr_feedback_splits_actionable_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(_cmd, cwd=None):
        return type(
            "R",
            (),
            {
                "stdout": json.dumps(
                    {
                        "comments": [
                            {"body": "review in progress by coderabbit.ai"},
                            {"body": "Looks good to me"},
                        ],
                        "reviews": [{"body": "Actionable comments posted: 2"}],
                    }
                )
            },
        )()

    monkeypatch.setattr("agvv.orchestration.pr_workflow._run", _fake_run)
    summary = summarize_pr_feedback("owner/repo", 1)
    assert len(summary.actionable) == 1
    assert len(summary.skipped) >= 1


def test_write_pr_feedback_file_creates_expected_content(tmp_path: Path) -> None:
    feedback = PrFeedbackSummary(actionable=["Fix lint"], skipped=["Informational bot comment"])
    feedback_path = write_pr_feedback_file(worktree=tmp_path, task_id="task-123", pr_number=99, feedback=feedback)
    assert feedback_path.exists()
    text = feedback_path.read_text(encoding="utf-8")
    assert "task=task-123 pr=99" in text
    assert "- Fix lint" in text
