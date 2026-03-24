"""Core data models for orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LayoutPaths:
    """Resolved filesystem paths for a project/worktree layout.

    Layout:
        <project>/
            .git/                # git repository metadata
            worktrees/           # extra task worktrees only
                feat-<slug>/    # one feature worktree per task
            docs/                # task specs and project documentation
            .gitignore          # excludes /worktrees/
            .gitattributes       # normalised line endings
    """

    project_dir: Path
    """Project root directory — also the main worktree directory."""
    repo_dir: Path
    """Git repository (.git directory inside project_dir)."""
    main_dir: Path
    """Main worktree directory (equals project_dir)."""
    worktrees_dir: Path
    """Directory containing all feature worktrees."""
    docs_dir: Path
    """Directory containing task specs and project documentation."""
    feature_dir: Path | None = None
    """Feature worktree directory, under worktrees_dir when set."""
