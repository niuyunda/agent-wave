from __future__ import annotations

from agvv.core import config, run, task
from agvv.core.models import RunMeta, RunPurpose, RunStatus, TaskStatus
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
        with self.assertRaisesRegex(ValueError, 'already exists'):
            task.add_task(repo, duplicate)

    def test_list_and_show_task_include_latest_run_metadata(self) -> None:
        repo = self._create_project_repo("task-metadata")
        self._add_task(repo, "metadata-task", "Checklist item.")

        run_file = config.runs_dir(repo, "metadata-task") / "001-review.md"
        meta = RunMeta(
            purpose=RunPurpose.review,
            agent="codex",
            status=RunStatus.failed,
            pid=123,
        )
        markdown.write_md(run_file, meta.model_dump(mode="json"), "summary text")

        listed = task.list_tasks(repo)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["run_number"], 1)
        self.assertEqual(listed[0]["last_purpose"], RunPurpose.review.value)
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
            run_file = config.runs_dir(repo, "numbered-task") / f"{run_number:03d}-implement.md"
            markdown.write_md(
                run_file,
                RunMeta(
                    purpose=RunPurpose.implement,
                    agent="codex",
                    status=RunStatus.completed,
                ).model_dump(mode="json"),
                "",
            )

        self.assertEqual(task.next_run_number(repo, "numbered-task"), 3)

    def test_merge_task_archives_task_and_removes_branch_resources(self) -> None:
        repo = self._create_project_repo("task-merge")
        self._add_task(repo, "merge-task", "SLEEP=0")

        run.start_run(repo, "merge-task", RunPurpose.implement, "success")
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
