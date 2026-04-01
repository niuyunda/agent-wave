"""Output formatting utilities."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def print_json(data: Any) -> None:
    """Print JSON output."""
    console.print_json(json.dumps(data, default=str))


def print_success(msg: str, **data: Any) -> None:
    payload = {"ok": True, "message": msg, **data}
    print_json(payload)


def print_error(msg: str) -> None:
    err_console.print(json.dumps({"ok": False, "error": msg}, default=str))


def print_info(msg: str, **data: Any) -> None:
    payload = {"ok": True, "message": msg, **data}
    print_json(payload)
