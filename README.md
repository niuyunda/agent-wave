# Agent Wave (`agvv`)

[中文文档 (README.zh-CN.md)](./README.zh-CN.md)

`agvv` runs coding tasks in isolated git worktrees and tracks task state safely with SQLite. It's designed to be a safe, concurrent execution environment for AI Agents like Codex or Claude.

## Key Features

1. **Total Isolation (`git worktree`)**: AI Agents write code in isolated feature worktrees. They will never pollute your main branch or current working directory.
2. **Concurrent Background Execution (`tmux`)**: Tasks run completely in the background. You can close your terminal and check back later.
3. **Resilient State Tracking (`sqlite3`)**: Prevents corrupted task states. Unlike JSON files, SQLite provides lock-safe concurrency and power-loss resilience, ensuring task history is never lost even if the daemon crashes.

## What You Need

- Python `>=3.10`
- `git`, `tmux`, `gh` (authenticated)
- `uv`

## Install

```bash
uv tool install agvv
agvv --help
```

From source:

```bash
uv sync --dev
uv run agvv --help
```

## Quick Start

### 1) Write `task.json` (core metadata only)

Keep this small. Put your actual prompt/requirements into `task_doc`.

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "task_doc": "./task.md"
}
```

### 2) Write `task.md`

This is where you explain to the AI Agent what you want it to code.

### 3) Start the task

Existing local repo:

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

Create new managed project under current directory (useful for greenfield projects):

```bash
agvv task run --spec ./task.json
```

### 4) Monitor progress

Check the status of your tasks:

```bash
agvv task status
```

Run the background daemon to update statuses (mark tasks as DONE or TIMED_OUT):

```bash
agvv daemon run --once
```

## Clean Up

When a task is done, you can delete the isolated worktree safely:

```bash
agvv task cleanup --task-id <task_id>
```

## Troubleshooting

- `tmux not found`: install `tmux`.
- `gh` auth issues: run `gh auth login`.
- `No git remote 'origin' configured`: add remote to managed repo, e.g. `git -C <base_dir>/<project_name>/repo.git remote add origin <repo-url>`.
