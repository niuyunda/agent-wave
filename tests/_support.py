from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

import frontmatter

from agvv.core import config, project, run, task
warnings.filterwarnings("ignore", category=DeprecationWarning, module="frontmatter")
warnings.filterwarnings("ignore", category=ResourceWarning, module="subprocess")


FAKE_AGENT_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

# Skip global options that may appear before the agent name.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --approve-all) shift || true ;;
    --timeout|--model|--cwd|--format) shift 2 || true ;;
    *) break ;;
  esac
done

agent="${1:-}"
shift || true

# Skip session-related flags before subcommand
session=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--session) session="${2:-}"; shift 2 || true ;;
    --cwd) shift 2 || true ;;       # ignore --cwd
    --format) shift 2 || true ;;    # ignore --format
    *) break ;;
  esac
done

# Handle session management subcommands
if [[ "${1:-}" == "sessions" ]]; then
  # sessions ensure / sessions close / sessions list / sessions show
  exit 0
fi

# Handle status subcommand
if [[ "${1:-}" == "status" ]]; then
  echo '{"status":"ok"}'
  exit 0
fi

prompt="${*:-}"
base_dir="${TMPDIR:-/tmp}/agvv-test-agent"
mkdir -p "$base_dir"
pid_file="$base_dir/${session}.pid"

if [[ "$prompt" == "cancel" ]]; then
  if [[ "$agent" == "no_cancel" ]]; then
    exit 1
  fi
  if [[ -f "$pid_file" ]]; then
    kill -TERM "$(cat "$pid_file")" 2>/dev/null || true
    exit 0
  fi
  exit 1
fi

echo "$$" > "$pid_file"
trap 'rm -f "$pid_file"' EXIT

sleep_seconds="$(echo "$prompt" | sed -n 's/.*SLEEP=\\([0-9][0-9]*\\).*/\\1/p' | head -n1)"
if [[ -z "$sleep_seconds" ]]; then
  sleep_seconds=1
fi

report_path="$(echo "$prompt" | sed -n 's/.*AGVV_REPORT_PATH=\\([^[:space:]]\\+\\).*/\\1/p' | head -n1)"
if [[ -n "$report_path" ]]; then
  mkdir -p "$(dirname "$report_path")"
  cat > "$report_path" <<REPORT
# Review Report

agent=$agent
session=${session:-none}
REPORT
fi

git_commit_if_possible() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local f=".fake-agent-${agent}-${session:-nosession}.txt"
    {
      echo "agent=$agent"
      echo "session=${session:-none}"
      echo "prompt=$(echo "$prompt" | tr '\\n' ' ')"
    } >> "$f"
    git add "$f" >/dev/null 2>&1 || true
    git commit -m "fake-agent: ${agent}" >/dev/null 2>&1 || true
  fi
}

case "$agent" in
  success|codex|claude|pi)
    sleep "$sleep_seconds"
    git_commit_if_possible
    exit 0
    ;;
  dirty_no_commit)
    sleep "$sleep_seconds"
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      printf '%s\n' "dirty-${session:-none}" >> ".dirty-no-commit.txt"
    fi
    exit 0
    ;;
  no_commit)
    sleep "$sleep_seconds"
    exit 0
    ;;
  fail)
    sleep "$sleep_seconds"
    exit 2
    ;;
  no_cancel)
    trap "" TERM
    while true; do
      sleep 1
    done
    ;;
  *)
    exit 3
    ;;
esac
"""


class AgvvRepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.home_dir = self.tmp_path / "home"
        self.home_dir.mkdir()

        self.projects_file = self.home_dir / ".agvv" / "projects.md"
        self.daemon_pid_file = self.home_dir / ".agvv" / "daemon.pid"
        self.daemon_log_file = self.home_dir / ".agvv" / "daemon.log"
        self.agvv_home = self.home_dir / ".agvv"
        self.agvv_home.mkdir(parents=True, exist_ok=True)

        self.config_patcher = mock.patch.multiple(
            config,
            AGVV_HOME=self.agvv_home,
            PROJECTS_FILE=self.projects_file,
            DAEMON_PID_FILE=self.daemon_pid_file,
            DAEMON_LOG_FILE=self.daemon_log_file,
        )
        self.config_patcher.start()

        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "AGVV_ACPX_BIN": str(self._write_fake_agent()),
                "AGVV_ACPX_ARGS": "",
                "AGVV_ACPX_OPTS": "",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        self.config_patcher.stop()
        self.tmp.cleanup()

    def _write_fake_agent(self) -> Path:
        script = self.tmp_path / "fake-acpx"
        script.write_text(FAKE_AGENT_SCRIPT, encoding="utf-8")
        script.chmod(0o755)
        return script

    def _create_project_repo(self, name: str, register: bool = True) -> Path:
        repo = self.tmp_path / name
        repo.mkdir()
        self._run(["git", "init", "-b", "main"], cwd=repo)
        self._run(["git", "config", "user.name", "agvv-test"], cwd=repo)
        self._run(["git", "config", "user.email", "agvv-test@example.com"], cwd=repo)
        (repo / "src").mkdir()
        (repo / "src" / "base.txt").write_text("initial\n", encoding="utf-8")
        (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        self._run(["git", "add", "."], cwd=repo)
        self._run(["git", "commit", "-m", "init"], cwd=repo)
        if register:
            project.add_project(repo)
        return repo

    def _add_task(self, repo: Path, name: str, body_suffix: str = "") -> None:
        task_file = self.tmp_path / f"{name}.md"
        task_file.write_text(
            textwrap.dedent(
                f"""\
                ---
                name: {name}
                ---

                ## Goal
                Task {name}.

                {body_suffix}
                """
            ),
            encoding="utf-8",
        )
        task.add_task(repo, task_file)

    def _write_project_config(self, repo: Path, **metadata: object) -> None:
        config_file = repo / ".agvv" / "config.md"
        config_file.write_text(
            frontmatter.dumps(frontmatter.Post("", **metadata)) + "\n",
            encoding="utf-8",
        )

    def _latest_run(self, repo: Path, task_name: str) -> dict:
        return task.show_task(repo, task_name)["runs"][-1]

    def _wait_for_active_run(self, repo: Path, task_name: str, timeout: float = 2.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            active = run.get_active_run(repo, task_name)
            if active and active.get("pgid"):
                return active
            time.sleep(0.05)
        self.fail(f"timed out waiting for active run {task_name}")

    def _wait_for_process_exit(self, repo: Path, task_name: str, timeout: float = 4.0) -> None:
        pid = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            active = run.get_active_run(repo, task_name)
            if active and active.get("pid"):
                pid = active["pid"]
                break
            runs = task.show_task(repo, task_name)["runs"]
            if runs and runs[-1].get("pid"):
                pid = runs[-1]["pid"]
                break
            time.sleep(0.05)
        if not pid:
            self.fail(f"timed out finding process for {task_name}")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._pid_exists(pid):
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for process exit {task_name}")

    def _wait_for_pid_exit(self, pid: int | None, timeout: float = 4.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._pid_exists(pid):
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for pid {pid} to exit")

    def _commit_in_worktree(self, worktree: Path, rel_path: str, content: str, message: str) -> None:
        target = worktree / rel_path
        target.write_text(content, encoding="utf-8")
        self._run(["git", "add", rel_path], cwd=worktree)
        self._run(["git", "commit", "-m", message], cwd=worktree)

    def _pid_exists(self, pid: int | None) -> bool:
        if not pid:
            return False
        proc_stat = Path(f"/proc/{pid}/stat")
        if proc_stat.exists():
            try:
                fields = proc_stat.read_text(encoding="utf-8").split()
                if len(fields) >= 3 and fields[2] == "Z":
                    return False
            except OSError:
                pass
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def _run(self, args: list[str], cwd: Path) -> None:
        subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
