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


def test_load_task_spec_ignores_agent_fields_from_spec(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-agent.json",
        {
            "project_name": "demo",
            "feature": "feat_agent",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "agent_cmd": "echo should-not-be-used",
            "agent": {
                "provider": "claude_code",
                "model": "sonnet",
                "extra_args": ["--approval-mode", "auto"],
            },
            "agent_model": "gpt-5",
            "agent_extra_args": ["--dangerously-skip-permissions"],
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.agent == "codex"
    assert spec.agent_model is None
    assert spec.agent_extra_args == []
    assert spec.agent_cmd == "codex"


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
            "acceptance_criteria": ["`GET /health` returns 200", "Unit tests pass"],
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.requirements == "Implement API endpoint for health check."
    assert spec.constraints == ["Do not change existing API schema.", "Use stdlib only."]
    assert spec.acceptance_criteria == ["`GET /health` returns 200", "Unit tests pass"]


def test_load_task_spec_rejects_invalid_acceptance_criteria_length(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-invalid-dod.json",
        {
            "project_name": "demo",
            "feature": "feat_bad_dod",
            "repo": "owner/repo",
            "acceptance_criteria": ["only one"],
        },
    )
    with pytest.raises(AgvvError, match="acceptance_criteria"):
        load_task_spec(spec_path)


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
