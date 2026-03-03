"""Command execution helpers for orchestration infrastructure."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, Sequence

from agvv.shared.errors import AgvvError


class CommandRunner(Protocol):
    """Typed callable contract for shell command execution."""

    def __call__(self, cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run a command and return captured process output."""


def run_checked(cmd: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a shell command and normalize failures into ``AgvvError``."""

    argv = [str(part) for part in cmd]
    if not argv:
        raise AgvvError("Command cannot be empty.")
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise AgvvError(f"Command not found: {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise AgvvError(
            f"Command failed: {' '.join(argv)}\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        ) from exc


def run_success(cmd: Sequence[str], cwd: Path | None = None) -> bool:
    """Return whether a command completes successfully."""

    try:
        run_checked(cmd, cwd=cwd)
        return True
    except AgvvError:
        return False


def run_git(args: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a ``git`` command with shared error handling."""

    return run_checked(["git", *args], cwd=cwd)


def run_git_success(args: Sequence[str], cwd: Path | None = None) -> bool:
    """Return whether a ``git`` command succeeds."""

    return run_success(["git", *args], cwd=cwd)
