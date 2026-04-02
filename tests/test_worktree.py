from __future__ import annotations

from agvv.core import worktree

from tests._support import AgvvRepoTestCase


class WorktreeTest(AgvvRepoTestCase):
    def test_ensure_worktree_rejects_path_traversal_task_name(self) -> None:
        repo = self._create_project_repo("worktree-path-traversal")

        with self.assertRaisesRegex(ValueError, "Path traversal detected"):
            worktree.ensure_worktree(repo, "../../worktree-path-traversal-evil")
