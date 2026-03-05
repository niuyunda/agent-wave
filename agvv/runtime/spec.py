"""Task specification loading utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agvv.shared.errors import AgvvError
from agvv.runtime.models import TaskSpec

_FRONT_MATTER_DELIM = "---"
_YAML_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_INT_RE = re.compile(r"^[+-]?\d+$")


def _split_task_md(raw: str) -> tuple[str, str]:
    """Split task.md into YAML front matter and Markdown body."""
    lines = raw.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIM:
        raise AgvvError(
            "Task spec must start with YAML front matter delimited by '---'."
        )

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONT_MATTER_DELIM:
            end_idx = idx
            break
    if end_idx is None:
        raise AgvvError("Task spec YAML front matter is missing a closing '---'.")

    yaml_text = "\n".join(lines[1:end_idx]).strip()
    body_text = "\n".join(lines[end_idx + 1 :]).strip()
    return yaml_text, body_text


def _strip_inline_comment(text: str) -> str:
    """Drop trailing YAML comments from an unquoted scalar."""
    in_single = False
    in_double = False
    escape = False
    for idx, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_double:
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "#" and not in_single and not in_double:
            if idx == 0 or text[idx - 1].isspace():
                return text[:idx].rstrip()
    return text.rstrip()


def _parse_inline_list(value: str) -> list[Any]:
    """Parse a simple YAML inline list: [a, b, c]."""
    inner = value[1:-1].strip()
    if not inner:
        return []

    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    escape = False
    for ch in inner:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\" and in_double:
            buf.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            continue
        if ch == "," and not in_single and not in_double:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf).strip())
    return [_parse_scalar(part) for part in parts]


def _parse_scalar(value: str) -> Any:
    """Parse a YAML scalar value in the supported subset."""
    token = _strip_inline_comment(value).strip()
    if token == "":
        return ""

    lower = token.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "~"}:
        return None
    if _INT_RE.fullmatch(token):
        return int(token)
    if token.startswith("[") and token.endswith("]"):
        return _parse_inline_list(token)
    if token.startswith('"') and token.endswith('"'):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return token[1:-1]
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1].replace("''", "'")
    return token


def _parse_simple_yaml_mapping(yaml_text: str) -> dict[str, Any]:
    """Parse a constrained YAML mapping (top-level scalars and string lists)."""
    content = yaml_text.strip()
    if not content:
        return {}

    # JSON object is a valid YAML subset; support it for compatibility.
    try:
        parsed_json = json.loads(content)
    except json.JSONDecodeError:
        parsed_json = None
    if isinstance(parsed_json, dict):
        return parsed_json
    if parsed_json is not None:
        raise AgvvError("Task spec front matter must be an object mapping.")

    payload: dict[str, Any] = {}
    pending_key: str | None = None
    pending_indent = 0
    pending_items: list[Any] = []

    for line_no, raw_line in enumerate(yaml_text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if pending_key is not None:
            if indent > pending_indent:
                stripped = raw_line.strip()
                if not stripped.startswith("- "):
                    raise AgvvError(
                        f"Invalid YAML at line {line_no}: only list items are supported for nested blocks."
                    )
                pending_items.append(_parse_scalar(stripped[2:]))
                continue
            payload[pending_key] = pending_items if pending_items else None
            pending_key = None
            pending_indent = 0
            pending_items = []

        stripped = raw_line.strip()
        match = _YAML_KEY_RE.match(stripped)
        if match is None:
            raise AgvvError(
                f"Invalid YAML at line {line_no}: expected '<key>: <value>' mapping."
            )
        key, raw_value = match.group(1), match.group(2)
        if key in payload:
            raise AgvvError(f"Duplicate YAML key '{key}' at line {line_no}.")

        if raw_value.strip() == "":
            pending_key = key
            pending_indent = indent
            pending_items = []
            continue
        payload[key] = _parse_scalar(raw_value)

    if pending_key is not None:
        payload[pending_key] = pending_items if pending_items else None

    return payload


def load_task_spec(path: Path) -> TaskSpec:
    """Load task spec from task.md (YAML front matter + Markdown body)."""
    if path.suffix.lower() != ".md":
        raise AgvvError("Task spec file must be a Markdown (.md) file.")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgvvError(f"Failed to read spec file at {path}: {exc}") from exc

    yaml_text, body_text = _split_task_md(raw)
    payload = _parse_simple_yaml_mapping(yaml_text)
    if not isinstance(payload, dict):
        raise AgvvError("Task spec front matter must be an object mapping.")
    if any(not isinstance(key, str) for key in payload):
        raise AgvvError("Task spec front matter keys must be strings.")
    if body_text:
        payload["requirements"] = body_text

    return TaskSpec.from_payload(payload, spec_dir=path.parent)
