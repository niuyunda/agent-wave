"""Markdown front-matter parsing utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter


def read_md(path: Path) -> frontmatter.Post:
    """Read a markdown file with front-matter."""
    return frontmatter.load(str(path))


def write_md(path: Path, metadata: dict[str, Any], content: str) -> None:
    """Write a markdown file with front-matter."""
    post = frontmatter.Post(content, **metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Read only the front-matter from a markdown file."""
    post = frontmatter.load(str(path))
    return dict(post.metadata)


def read_body(path: Path) -> str:
    """Read only the body from a markdown file."""
    post = frontmatter.load(str(path))
    return post.content
