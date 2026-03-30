"""Shared acpx invocation helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def acpx_invocation() -> tuple[str, list[str]]:
    """Resolve the acpx launcher at call time.

    This keeps tests and CLI invocations deterministic when env vars change
    between calls.

    Environment variables:
        AGVV_ACPX_BIN: Override the acpx binary path
        AGVV_ACPX_ARGS: Additional arguments for acpx (space-separated)
    """
    env_bin = os.environ.get("AGVV_ACPX_BIN")
    env_args = os.environ.get("AGVV_ACPX_ARGS")
    if env_bin is not None or env_args is not None:
        return (
            env_bin or "npx",
            env_args.split() if env_args is not None else ["acpx@latest"],
        )

    local_acpx = shutil.which("acpx")
    if local_acpx:
        return (local_acpx, [])

    return ("npx", ["acpx@latest"])


def acpx_opts() -> list[str]:
    """Read agent options from AGVV_ACPX_OPTS.

    These are flags like --approve-all or --model that go before the agent name.
    """
    raw = os.environ.get("AGVV_ACPX_OPTS", "")
    return raw.split() if raw else []


def check_acpx_auth() -> str | None:
    """Check if acpx has valid authentication configured.

    Returns None if auth looks OK, otherwise returns a diagnostic message.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        if openai_key.startswith("sk-or-v1-"):
            return "Warning: OPENAI_API_KEY starts with 'sk-or-v1-' (OpenRouter). Codex may need OpenAI API key."

    codex_auth = Path.home() / ".codex" / "auth.json"
    if codex_auth.exists():
        try:
            import json
            auth_data = json.loads(codex_auth.read_text())
            auth_mode = auth_data.get("auth_mode", "unknown")
            api_key = auth_data.get("OPENAI_API_KEY")

            if auth_mode == "apikey" and api_key:
                if api_key.startswith("sk-or-v1-"):
                    return "Codex auth.json has OpenRouter key - may cause 401 errors"
            elif auth_mode == "chatgpt":
                return None
        except Exception:
            pass

    return None
