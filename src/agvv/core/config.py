"""Global configuration and path conventions."""

from __future__ import annotations

from pathlib import Path

AGVV_DIR = ".agvv"
TASKS_DIR = "tasks"
ARCHIVE_DIR = "archive"
RUNS_DIR = "runs"
CONFIG_FILE = "config.md"
TASK_FILE = "task.md"
BRANCH_PREFIX = "agvv/"

# Task name validation pattern
TASK_NAME_PATTERN = r"^[A-Za-z0-9._-]+$"

# Global home directory
AGVV_HOME = Path.home() / ".agvv"
PROJECTS_FILE = AGVV_HOME / "projects.md"
DAEMON_PID_FILE = AGVV_HOME / "daemon.pid"
DAEMON_LOG_FILE = AGVV_HOME / "daemon.log"

# Defaults
DEFAULT_RUN_TIMEOUT = 3600  # 1 hour
DEFAULT_STALL_TIMEOUT = 300  # 5 minutes no output


def ensure_agvv_home() -> Path:
    AGVV_HOME.mkdir(parents=True, exist_ok=True)
    return AGVV_HOME


def project_agvv_dir(project_path: Path) -> Path:
    return project_path / AGVV_DIR


def tasks_dir(project_path: Path) -> Path:
    return project_agvv_dir(project_path) / TASKS_DIR


def archive_dir(project_path: Path) -> Path:
    return tasks_dir(project_path) / ARCHIVE_DIR


def task_dir(project_path: Path, task_name: str) -> Path:
    return tasks_dir(project_path) / task_name


def task_file(project_path: Path, task_name: str) -> Path:
    return task_dir(project_path, task_name) / TASK_FILE


def runs_dir(project_path: Path, task_name: str) -> Path:
    return task_dir(project_path, task_name) / RUNS_DIR
