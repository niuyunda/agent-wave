"""Task spec loading behavior tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agvv.runtime.spec import load_task_spec
from agvv.shared.errors import AgvvError


def _write_spec(path: Path, payload: dict) -> Path:
    if "task_doc" not in payload:
        task_doc_path = path.with_suffix(".md")
        task_doc_path.write_text("# Task Doc\n\n- Test task details.\n", encoding="utf-8")
        payload["task_doc"] = str(task_doc_path)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_task_spec_json_success(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task.json",
        {
            "project_name": "demo",
            "feature": "feat_1",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.task_id.startswith("demo-feat_1-")
    assert spec.base_dir == tmp_path.resolve()
    assert spec.timeout_minutes == 240
    assert spec.agent_cmd == "codex"


def test_load_task_spec_ignores_agent_provider_fields_from_spec(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-agent.json",
        {
            "project_name": "demo",
            "feature": "feat_agent",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            # These runtime-controlled fields are intentionally ignored:
            "agent_cmd": "echo should-not-be-used",
            "agent": {"provider": "claude_code", "model": "sonnet"},
            "agent_model": "gpt-5",
            # agent_extra_args IS honored (carries codex flags, not provider choice):
            "agent_extra_args": ["--dangerously-skip-permissions"],
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.agent == "codex"
    assert spec.agent_model is None
    assert spec.agent_extra_args == ["--dangerously-skip-permissions"]
    assert spec.agent_cmd == "codex --dangerously-skip-permissions"


def test_load_task_spec_resolves_relative_task_doc_against_spec_dir(tmp_path: Path) -> None:
    task_doc = tmp_path / "task.md"
    task_doc.write_text("# Task\n", encoding="utf-8")
    spec_path = tmp_path / "task.json"
    spec_path.write_text(
        json.dumps(
            {
                "project_name": "demo",
                "feature": "feat_reldoc",
                "repo": "owner/repo",
                "task_doc": "./task.md",  # relative — must resolve to tmp_path/task.md
            }
        ),
        encoding="utf-8",
    )
    spec = load_task_spec(spec_path)
    assert spec.task_doc == task_doc.resolve()


def test_load_task_spec_ignores_task_id_from_spec(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-ignore-id.json",
        {
            "project_name": "demo",
            "feature": "feat_ignore_id",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "task_id": "custom-id-should-be-ignored",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.task_id.startswith("demo-feat_ignore_id-")
    assert spec.task_id != "custom-id-should-be-ignored"


def test_load_task_spec_fails_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(AgvvError, match="Failed to read spec file"):
        load_task_spec(tmp_path / "missing-spec.json")


def test_load_task_spec_rejects_non_object_payload(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-invalid-root.json"
    spec_path.write_text('["not-an-object"]', encoding="utf-8")
    with pytest.raises(AgvvError, match="Task spec must be an object"):
        load_task_spec(spec_path)


def test_load_task_spec_rejects_invalid_json(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-invalid-json.txt"
    spec_path.write_text("::: invalid :::", encoding="utf-8")
    with pytest.raises(AgvvError, match="not valid JSON"):
        load_task_spec(spec_path)


def test_load_task_spec_defaults_base_dir_to_cwd(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-missing-base-dir.json",
        {
            "task_id": "task_missing_base_dir",
            "project_name": "demo",
            "feature": "feat_missing_base_dir",
            "repo": "owner/repo",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.base_dir == Path.cwd().resolve()


def test_load_task_spec_forces_from_branch_main(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-force-main.json",
        {
            "project_name": "demo",
            "feature": "feat_branch",
            "repo": "owner/repo",
            "from_branch": "release",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.from_branch == "main"


def test_load_task_spec_parses_requirement_contract_fields(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-contract.json",
        {
            "task_id": "task_contract",
            "project_name": "demo",
            "feature": "feat_contract",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "requirements": "Implement API endpoint for health check.",
            "constraints": ["Do not change existing API schema.", "Use stdlib only."],
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.requirements == "Implement API endpoint for health check."
    assert spec.constraints == ["Do not change existing API schema.", "Use stdlib only."]


def test_load_task_spec_rejects_feature_with_spaces(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-invalid-feature.json",
        {
            "project_name": "demo",
            "feature": "bad feature",
            "repo": "owner/repo",
        },
    )
    with pytest.raises(AgvvError, match="feature"):
        load_task_spec(spec_path)


# ---------------------------------------------------------------------------
# from_payload / from_db_payload round-trip semantics
# ---------------------------------------------------------------------------

def test_from_payload_resets_runtime_controlled_fields(tmp_path: Path) -> None:
    """from_payload must reset agent, from_branch, task_id regardless of spec content.

    Note: agent_extra_args is intentionally preserved — it carries agent flags
    (not provider choice) and may legitimately appear in user spec files.
    """
    task_doc = tmp_path / "task.md"
    task_doc.write_text("# Task\n", encoding="utf-8")

    payload = {
        "project_name": "demo",
        "feature": "feat_rt",
        "repo": "owner/repo",
        "task_doc": str(task_doc),
        # Runtime-controlled fields that must be reset:
        "agent": "claude_code",
        "from_branch": "release",
        "task_id": "custom-id-must-not-survive",
        # agent_extra_args is deliberately absent: verified separately below
    }

    from agvv.runtime.models import TaskSpec
    spec = TaskSpec.from_payload(payload)

    # agent is always reset to codex
    assert spec.agent == "codex", f"expected agent='codex', got {spec.agent!r}"
    # from_branch is always reset to main
    assert spec.from_branch == "main", f"expected from_branch='main', got {spec.from_branch!r}"
    # task_id is regenerated (different from the supplied custom id)
    assert spec.task_id != "custom-id-must-not-survive"
    assert spec.task_id.startswith("demo-feat_rt-")
    # agent_cmd is recomputed from the reset provider with no extra args
    assert spec.agent_cmd == "codex"


def test_from_db_payload_preserves_stored_values_and_recomputes_agent_cmd(tmp_path: Path) -> None:
    """from_db_payload must preserve stored provider/from_branch and recompute agent_cmd correctly."""
    task_doc = tmp_path / "task.md"
    task_doc.write_text("# Task\n", encoding="utf-8")

    from agvv.runtime.models import TaskSpec

    # Simulate what to_payload() stores in the DB for a claude_code task
    db_payload = {
        "task_id": "demo-feat_db-abc123",
        "project_name": "demo",
        "feature": "feat_db",
        "repo": "owner/repo",
        "task_doc": str(task_doc),
        "from_branch": "release",
        "agent_model": "claude-sonnet-4-5",
        "agent_extra_args": [],
        "agent_non_interactive": True,
        "base_dir": str(tmp_path),
        # to_payload() serialises agent as a nested dict:
        "agent": {"provider": "claude_code", "model": "claude-sonnet-4-5", "extra_args": []},
        # agent_cmd is intentionally present but must be dropped and recomputed:
        "agent_cmd": "claude --stale-cached-value",
        "session": "demo-feat_db",
        "ticket": None,
        "requirements": None,
        "constraints": [],
        "timeout_minutes": 240,
    }

    spec = TaskSpec.from_db_payload(db_payload)

    # Stored values must be preserved
    assert spec.task_id == "demo-feat_db-abc123"
    assert spec.agent == "claude_code"
    assert spec.from_branch == "release"
    assert spec.agent_model == "claude-sonnet-4-5"
    # agent_cmd is recomputed from the stored provider, not taken from the stale cached value
    assert "claude" in spec.agent_cmd
    assert "stale-cached-value" not in spec.agent_cmd
