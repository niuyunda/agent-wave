"""Task spec loading behavior tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agvv.runtime.spec import load_task_spec
from agvv.shared.errors import AgvvError


def _write_spec(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_task_spec_json_success(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task.json",
        {
            "task_id": "task_1",
            "project_name": "demo",
            "feature": "feat_1",
            "agent_cmd": "echo build",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.task_id == "task_1"
    assert spec.base_dir == tmp_path.resolve()
    assert spec.timeout_minutes == 240


def test_load_task_spec_builds_agent_cmd_from_agent_object(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-agent.json",
        {
            "task_id": "task_structured_agent",
            "project_name": "demo",
            "feature": "feat_agent",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "agent": {
                "provider": "codex",
                "model": "gpt-5",
                "extra_args": ["--approval-mode", "auto"],
            },
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.agent == "codex"
    assert spec.agent_model == "gpt-5"
    assert spec.agent_extra_args == ["--approval-mode", "auto"]
    assert spec.agent_cmd == "codex --model gpt-5 --approval-mode auto"


def test_load_task_spec_rejects_unknown_agent_provider(tmp_path: Path) -> None:
    spec_path = _write_spec(
        tmp_path / "task-invalid-agent.json",
        {
            "task_id": "task_invalid_agent",
            "project_name": "demo",
            "feature": "feat_agent",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "agent": {"provider": "unknown-agent"},
        },
    )
    with pytest.raises(AgvvError, match="Unsupported agent provider"):
        load_task_spec(spec_path)


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
