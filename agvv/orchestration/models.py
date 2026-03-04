"""Core data models for orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LayoutPaths:
    """Resolved filesystem paths for a project/worktree layout."""

    project_dir: Path
    repo_dir: Path
    main_dir: Path
    feature_dir: Path | None = None
