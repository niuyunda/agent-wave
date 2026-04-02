from __future__ import annotations

import textwrap

import frontmatter

from agvv.core import config, run, task
from agvv.core.models import RunMeta, RunStatus, TaskStatus
from agvv.daemon import server
from agvv.utils import git, markdown

from tests._support import AgvvRepoTestCase


class TaskTest(AgvvRepoTestCase):
    def test_add_task_rejects_invalid_name_and_duplicates(self) -> None:
        repo = self._create_project_repo("task-validation")

        invalid = self.tmp_path / "invalid-task.md"
        invalid.write_text("---\nname: invalid/name\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid task name"):
            task.add_task(repo, invalid)

        self._add_task(repo, "duplicate-task")
        duplicate = self.tmp_path / "duplicate-task.md"
        duplicate.write_text("---\nname: duplicate-task\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists"):
            task.add_task(repo, duplicate)

    def test_add_task_preserves_extra_frontmatter(self) -> None:
        repo = self._create_project_repo("task-frontmatter-merge")
        src = self.tmp_path / "rich-task.md"
        src.write_text(
            textwrap.dedent(
                """\
                ---
                name: rich-task
                title: "Auth timeout"
                priority: high
                labels:
                  - security
                  - api
                links:
                  issue: "https://example.com/i/1"
                ---

                Body line.
                """
            ),
            encoding="utf-8",
        )
        task.add_task(repo, src)

        tf = config.task_file(repo, "rich-task")
        meta = frontmatter.load(str(tf)).metadata
        self.assertEqual(meta["name"], "rich-task")
        self.assertEqual(meta["title"], "Auth timeout")
        self.assertEqual(meta["priority"], "high")
        self.assertEqual(meta["labels"], ["security", "api"])
        self.assertEqual(meta["links"], {"issue": "https://example.com/i/1"})
        self.assertIn("status", meta)
        self.assertIn("created_at", meta)
        body = frontmatter.load(str(tf)).content
        self.assertIn("Body line.", body)

    def test_add_task_agent_option_overrides_source_frontmatter(self) -> None:
        repo = self._create_project_repo("task-agent-override")
        src = self.tmp_path / "agent-task.md"
        src.write_text(
            textwrap.dedent(
                """\
                ---
                name: agent-task
                agent: claude
                ---

                Task body.
                """
            ),
            encoding="utf-8",
        )
        task.add_task(repo, src, agent="codex")

        tf = config.task_file(repo, "agent-task")
        meta = frontmatter.load(str(tf)).metadata
        self.assertEqual(meta["agent"], "codex")

    def test_add_task_rejects_invalid_status_in_source(self) -> None:
        repo = self._create_project_repo("task-bad-status")
        src = self.tmp_path / "bad-status.md"
        src.write_text(
            "---\nname: bad-status-task\nstatus: not-a-real-status\n---\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Invalid task status"):
            task.add_task(repo, src)

    def test_list_and_show_task_include_latest_run_metadata(self) -> None:
        repo = self._create_project_repo("task-metadata")
        self._add_task(repo, "metadata-task", "Checklist item.")

        run_file = config.runs_dir(repo, "metadata-task") / "001.md"
        meta = RunMeta(
            agent="codex",
            status=RunStatus.failed,
            pid=123,
        )
        markdown.write_md(run_file, meta.model_dump(mode="json"), "summary text")

        listed = task.list_tasks(repo)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["run_number"], 1)
        self.assertEqual(listed[0]["last_agent"], "codex")
        self.assertEqual(listed[0]["last_status"], RunStatus.failed.value)
        self.assertEqual(listed[0]["last_event"], RunStatus.failed.value)

        info = task.show_task(repo, "metadata-task")
        self.assertEqual(info["branch"], "agvv/metadata-task")
        self.assertIn("Checklist item.", info["body"])
        self.assertEqual(info["runs"][0]["body"], "summary text")
        self.assertEqual(info["runs"][0]["status"], RunStatus.failed.value)

    def test_next_run_number_counts_existing_run_files(self) -> None:
        repo = self._create_project_repo("run-numbering")
        self._add_task(repo, "numbered-task")

        self.assertEqual(task.next_run_number(repo, "numbered-task"), 1)

        for run_number in (1, 2):
            run_file = (
                config.runs_dir(repo, "numbered-task") / f"{run_number:03d}.md"
            )
            markdown.write_md(
                run_file,
                RunMeta(
                    agent="codex",
                    status=RunStatus.completed,
                ).model_dump(mode="json"),
                "",
            )

        self.assertEqual(task.next_run_number(repo, "numbered-task"), 3)

    def test_list_tasks_skips_invalid_task_files_without_name(self) -> None:
        repo = self._create_project_repo("task-list-invalid")
        bad_task_file = config.tasks_dir(repo) / "broken-entry" / config.TASK_FILE
        bad_task_file.parent.mkdir(parents=True, exist_ok=True)
        bad_task_file.write_text("---\nstatus: pending\n---\n", encoding="utf-8")

        listed = task.list_tasks(repo)
        self.assertEqual(listed, [])

    def test_merge_task_archives_task_and_removes_branch_resources(self) -> None:
        repo = self._create_project_repo("task-merge")
        self._add_task(repo, "merge-task", "SLEEP=0")

        run.start_run(repo, "merge-task", "success")
        self._wait_for_process_exit(repo, "merge-task")
        server._monitor_cycle()

        merged_commit = task.merge_task(repo, "merge-task")

        self.assertEqual(merged_commit, git.get_latest_commit(repo))
        self.assertFalse(config.task_dir(repo, "merge-task").exists())
        self.assertFalse((repo / "worktrees" / "merge-task").exists())
        self.assertEqual(task.count_archived_tasks(repo), 1)

        archived_entries = list(config.archive_dir(repo).iterdir())
        self.assertEqual(len(archived_entries), 1)
        archived_task = archived_entries[0] / config.TASK_FILE
        self.assertEqual(
            markdown.read_frontmatter(archived_task)["status"],
            TaskStatus.done.value,
        )

        with self.assertRaises(git.GitError):
            git.run_git(["rev-parse", "--verify", "agvv/merge-task"], cwd=repo)

    def test_add_task_rejects_name_that_already_exists_in_archive(self) -> None:
        repo = self._create_project_repo("task-archive-name-reuse")
        self._add_task(repo, "repeat-task", "SLEEP=0")

        run.start_run(repo, "repeat-task", "success")
        self._wait_for_process_exit(repo, "repeat-task")
        server._monitor_cycle()
        task.merge_task(repo, "repeat-task")

        with self.assertRaisesRegex(ValueError, 'task "repeat-task" already exists'):
            self._add_task(repo, "repeat-task")

    def test_merge_task_requires_clean_project_worktree(self) -> None:
        repo = self._create_project_repo("task-merge-dirty")
        self._add_task(repo, "merge-task", "SLEEP=0")

        run.start_run(repo, "merge-task", "success")
        self._wait_for_process_exit(repo, "merge-task")
        server._monitor_cycle()

        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "has uncommitted changes"):
            task.merge_task(repo, "merge-task")

    def test_merge_task_requires_main_branch_in_project_worktree(self) -> None:
        repo = self._create_project_repo("task-merge-branch")
        self._add_task(repo, "merge-task", "SLEEP=0")

        run.start_run(repo, "merge-task", "success")
        self._wait_for_process_exit(repo, "merge-task")
        server._monitor_cycle()

        self._run(["git", "checkout", "-b", "feature"], cwd=repo)

        with self.assertRaisesRegex(ValueError, "checkout 'main' and rerun merge"):
            task.merge_task(repo, "merge-task")
