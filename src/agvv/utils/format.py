"""Output formatting utilities."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def print_table(columns: list[str], rows: list[list[str]], title: str | None = None) -> None:
    """Print a formatted table."""
    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col, style="bold" if col == columns[0] else None)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def print_json(data: Any) -> None:
    """Print JSON output."""
    console.print_json(json.dumps(data, default=str))


def print_success(msg: str) -> None:
    console.print(f"[green]{msg}[/green]")


def print_error(msg: str) -> None:
    err_console.print(f"[red]Error:[/red] {msg}")


def print_info(msg: str) -> None:
    console.print(msg)
