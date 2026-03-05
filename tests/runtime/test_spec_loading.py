"""Task spec loading behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agvv.runtime.models import TaskSpec, build_agent_command, normalize_agent_provider
from agvv.runtime.spec import load_task_spec
from agvv.shared.errors import AgvvError


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if (
        text == ""
        or text != text.strip()
        or ":" in text
        or "#" in text
        or text.startswith(("[", "{", "-", "!", "&", "*", "@", "`", '"', "'"))
    ):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _render_front_matter(payload: dict[str, object]) -> str:
    lines: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_yaml_scalar(item)}")
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")
    return "\n".join(lines)


def _write_task_md(
    path: Path, payload: dict[str, object], body: str | None = None
) -> Path:
    task_body = body if body is not None else "# Task Doc\n\n- Test task details.\n"
    front_matter = _render_front_matter(payload)
    content = f"---\n{front_matter}\n---\n"
    if task_body:
        content += f"\n{task_body.strip()}\n"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_task_spec_md_success(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task.md",
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
    assert spec.requirements == "# Task Doc\n\n- Test task details."


def test_load_task_spec_ignores_agent_provider_fields_from_spec(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-agent.md",
        {
            "project_name": "demo",
            "feature": "feat_agent",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            # These runtime-controlled fields are intentionally ignored:
            "agent_cmd": "echo should-not-be-used",
            "agent": "claude_code",
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


def test_load_task_spec_prefers_markdown_body_as_requirements(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-prefer-body.md",
        {
            "project_name": "demo",
            "feature": "feat_body",
            "repo": "owner/repo",
            "requirements": "front matter value that should be overridden",
        },
        body="# Goal\n\nUse body text.",
    )
    spec = load_task_spec(spec_path)
    assert spec.requirements == "# Goal\n\nUse body text."


def test_load_task_spec_honors_yaml_requirements_when_body_empty(
    tmp_path: Path,
) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-front-req.md",
        {
            "project_name": "demo",
            "feature": "feat_front_req",
            "repo": "owner/repo",
            "requirements": "Use front matter requirements.",
        },
        body="",
    )
    spec = load_task_spec(spec_path)
    assert spec.requirements == "Use front matter requirements."


def test_load_task_spec_supports_legacy_task_doc_field(tmp_path: Path) -> None:
    legacy_doc = tmp_path / "legacy.md"
    legacy_doc.write_text("# Legacy task\n", encoding="utf-8")
    spec_path = _write_task_md(
        tmp_path / "task-legacy.md",
        {
            "project_name": "demo",
            "feature": "feat_legacy",
            "repo": "owner/repo",
            "task_doc": "./legacy.md",
        },
        body="",
    )
    spec = load_task_spec(spec_path)
    assert spec.task_doc == legacy_doc.resolve()
    assert spec.requirements is None


def test_load_task_spec_ignores_task_id_from_spec(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-ignore-id.md",
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


def test_load_task_spec_rejects_blank_markdown_body_and_missing_requirements(
    tmp_path: Path,
) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-blank.md",
        {"project_name": "demo", "feature": "feat_blank"},
        body="",
    )
    with pytest.raises(AgvvError, match="requirements"):
        load_task_spec(spec_path)


def test_load_task_spec_fails_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(AgvvError, match="Failed to read spec file"):
        load_task_spec(tmp_path / "missing-spec.md")


def test_load_task_spec_rejects_non_markdown_spec_path(tmp_path: Path) -> None:
    bad_path = tmp_path / "task.json"
    bad_path.write_text("{}", encoding="utf-8")
    with pytest.raises(AgvvError, match="Markdown"):
        load_task_spec(bad_path)


def test_load_task_spec_rejects_non_object_front_matter(tmp_path: Path) -> None:
    spec_path = tmp_path / "task.md"
    spec_path.write_text("---\n[1, 2, 3]\n---\n\nTask body\n", encoding="utf-8")
    with pytest.raises(AgvvError, match="object mapping"):
        load_task_spec(spec_path)


def test_load_task_spec_rejects_missing_front_matter_delimiters(tmp_path: Path) -> None:
    spec_path = tmp_path / "task.md"
    spec_path.write_text("project_name: demo\nfeature: feat\n", encoding="utf-8")
    with pytest.raises(AgvvError, match="start with YAML front matter"):
        load_task_spec(spec_path)


def test_load_task_spec_rejects_unclosed_front_matter(tmp_path: Path) -> None:
    spec_path = tmp_path / "task.md"
    spec_path.write_text("---\nproject_name: demo\nfeature: feat\n", encoding="utf-8")
    with pytest.raises(AgvvError, match="closing '---'"):
        load_task_spec(spec_path)


def test_load_task_spec_rejects_invalid_yaml_mapping_line(tmp_path: Path) -> None:
    spec_path = tmp_path / "task.md"
    spec_path.write_text(
        "---\nproject_name: demo\nfeature feat_bad\n---\n\nTask body\n",
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="Invalid YAML"):
        load_task_spec(spec_path)


def test_load_task_spec_treats_comment_only_scalar_as_null(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-comment-null.md"
    spec_path.write_text(
        "---\nproject_name: demo\nfeature: feat_comment_null\nrepo: # optional\n---\n\nTask body\n",
        encoding="utf-8",
    )
    spec = load_task_spec(spec_path)
    assert spec.repo is None


def test_load_task_spec_rejects_unterminated_quoted_scalar(tmp_path: Path) -> None:
    spec_path = tmp_path / "task-unterminated-quote.md"
    spec_path.write_text(
        '---\nproject_name: demo\nfeature: "feat_bad\n---\n\nTask body\n',
        encoding="utf-8",
    )
    with pytest.raises(AgvvError, match="unterminated double-quoted scalar"):
        load_task_spec(spec_path)


def test_load_task_spec_defaults_base_dir_to_cwd(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-missing-base-dir.md",
        {
            "task_id": "task_missing_base_dir",
            "project_name": "demo",
            "feature": "feat_missing_base_dir",
            "repo": "owner/repo",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.base_dir == Path.cwd().resolve()


def test_load_task_spec_honors_user_specified_from_branch(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-from-branch.md",
        {
            "project_name": "demo",
            "feature": "feat_branch",
            "repo": "owner/repo",
            "from_branch": "release",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.from_branch == "release"


def test_load_task_spec_defaults_from_branch_to_main_when_absent(
    tmp_path: Path,
) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-no-branch.md",
        {
            "project_name": "demo",
            "feature": "feat_default_branch",
            "repo": "owner/repo",
        },
    )
    spec = load_task_spec(spec_path)
    assert spec.from_branch == "main"


def test_load_task_spec_parses_requirement_contract_fields(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-contract.md",
        {
            "task_id": "task_contract",
            "project_name": "demo",
            "feature": "feat_contract",
            "repo": "owner/repo",
            "base_dir": str(tmp_path),
            "constraints": ["Do not change existing API schema.", "Use stdlib only."],
            "timeout_minutes": 90,
        },
        body="Implement API endpoint for health check.",
    )
    spec = load_task_spec(spec_path)
    assert spec.requirements == "Implement API endpoint for health check."
    assert spec.constraints == [
        "Do not change existing API schema.",
        "Use stdlib only.",
    ]
    assert spec.timeout_minutes == 90


def test_load_task_spec_rejects_feature_with_spaces(tmp_path: Path) -> None:
    spec_path = _write_task_md(
        tmp_path / "task-invalid-feature.md",
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

    Note: agent_extra_args is intentionally preserved - it carries agent flags
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

    spec = TaskSpec.from_payload(payload)

    # agent is always reset to codex
    assert spec.agent == "codex", f"expected agent='codex', got {spec.agent!r}"
    # from_branch is preserved when the user specifies one
    assert spec.from_branch == "release", (
        f"expected from_branch='release', got {spec.from_branch!r}"
    )
    # task_id is regenerated (different from the supplied custom id)
    assert spec.task_id != "custom-id-must-not-survive"
    assert spec.task_id.startswith("demo-feat_rt-")
    # agent_cmd is recomputed from the reset provider with no extra args
    assert spec.agent_cmd == "codex"


def test_from_db_payload_preserves_stored_values_and_recomputes_agent_cmd(
    tmp_path: Path,
) -> None:
    """from_db_payload must preserve stored provider/from_branch and recompute agent_cmd correctly."""
    task_doc = tmp_path / "task.md"
    task_doc.write_text("# Task\n", encoding="utf-8")

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
        "agent": {
            "provider": "claude_code",
            "model": "claude-sonnet-4-5",
            "extra_args": [],
        },
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "codex"),
        ("", "codex"),
        (" codex ", "codex"),
        ("CLAUDE", "claude_code"),
        ("claude-code", "claude_code"),
        ("claude_code", "claude_code"),
    ],
)
def test_normalize_agent_provider_aliases(raw: str | None, expected: str) -> None:
    assert normalize_agent_provider(raw) == expected


def test_normalize_agent_provider_rejects_unknown_value() -> None:
    with pytest.raises(AgvvError, match="Unsupported agent provider"):
        normalize_agent_provider("unknown-provider")


@pytest.mark.parametrize(
    ("provider", "model", "extra_args", "expected"),
    [
        ("codex", None, [], "codex"),
        (
            "codex",
            "gpt-5",
            ["--sandbox", "workspace-write"],
            "codex --model gpt-5 --sandbox workspace-write",
        ),
        (
            "claude_code",
            None,
            ["--print", "hello world"],
            "claude --print 'hello world'",
        ),
    ],
)
def test_build_agent_command(
    provider: str, model: str | None, extra_args: list[str], expected: str
) -> None:
    assert build_agent_command(provider, model, extra_args) == expected


def test_build_agent_command_rejects_unknown_provider() -> None:
    with pytest.raises(AgvvError, match="Unsupported agent provider"):
        build_agent_command("unsupported", None, [])


def test_taskspec_normalized_session_defaults_to_agvv_task_id() -> None:
    spec = TaskSpec.from_payload(
        {
            "project_name": "demo",
            "feature": "feat_default_session",
            "requirements": "Implement feature.",
        }
    )
    assert spec.normalized_session() == f"agvv-{spec.task_id}"


def test_taskspec_normalized_session_preserves_explicit_session() -> None:
    spec = TaskSpec.from_payload(
        {
            "project_name": "demo",
            "feature": "feat_custom_session",
            "requirements": "Implement feature.",
            "session": "agvv-custom",
        }
    )
    assert spec.normalized_session() == "agvv-custom"
