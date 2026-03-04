# Agent Wave Skill (`agvv`)

[中文说明 (README.zh-CN.md)](./README.zh-CN.md)

Agent Wave is a tool for coding agents.  
It gives each task an isolated Git worktree, runs the agent in `tmux`, tracks task state in SQLite, and helps move work from coding to PR.

This repository will be packaged as a reusable skill.  
This README focuses on how users and agents should use the skill in daily work.

## Who This Is For

- Designed for coding tasks run by AI agents.
- Safer parallel work without direct edits in the main branch workspace.
- Simple command flow to run, monitor, retry, and clean tasks.

## What The Skill Does

For each task, Agent Wave will:

1. Create a feature worktree in a standard project layout.
2. Start an agent command in a dedicated `tmux` session.
3. Track task lifecycle and errors in a local SQLite DB.
4. Help finalize code into a PR and follow PR feedback loops.
5. Support retry and cleanup commands for operations.

## Requirements

- Python `>=3.10`
- `git`
- `tmux`
- `gh` (GitHub CLI, authenticated)
- `uv`

## Install And Check

```bash
uv tool install agvv
agvv --help
```

If you use this as a skill, make sure `agvv` is available in the environment where the agent runs.
For local development from source, use `uv sync --dev` and run CLI commands as `uv run agvv ...`.
If you want to use YAML task specs, install PyYAML first (for example: `uv add pyyaml`).

## 5-Minute Quick Start

### 1) Create a task spec file

Create `task.json`:

```json
{
  "task_id": "demo_task_1",
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "base_dir": "~/Code",
  "from_branch": "main",
  "agent": {
    "provider": "codex",
    "model": "gpt-5",
    "extra_args": ["--approval-mode", "auto"]
  },
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo",
  "pr_body": "Implement demo feature",
  "timeout_minutes": 240,
  "max_retry_cycles": 5,
  "auto_cleanup": true
}
```

### 2) Start the task

```bash
agvv task run --spec ./task.json
```

Expected output includes task id, state, and tmux session name.

### 3) Check status

```bash
agvv task status
```

### 4) Reconcile once (daemon single pass)

```bash
agvv daemon run --once
```

This is the core loop for the skill: it checks active tasks and advances their state.

## Command Guide (User-Facing)

### `project init`

Initialize an Agent Wave project layout:

```bash
agvv project init --project-name demo [--base-dir ~/code]
```

Common use: create a managed bare repo + `main` worktree structure before running tasks.

### `project adopt`

Adopt an existing local git repository into Agent Wave layout:

```bash
agvv project adopt --project-name demo --repo /path/to/repo [--base-dir ~/code]
```

Common use: migrate an existing repository into Agent Wave-managed worktree layout.

### `task run`

Create and launch one task from spec:

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--model gpt-5]
```

Common use: start new work with optional temporary agent/model override.

### `task status`

List tasks and current state:

```bash
agvv task status [--db-path ./tasks.db] [--task-id demo_task_1] [--state coding]
```

Common use: monitor many tasks or filter one task.

### `task retry`

Retry a recoverable task:

```bash
agvv task retry --task-id demo_task_1 [--db-path ./tasks.db] [--session custom-session]
```

Common use: resume after failure, timeout, or PR feedback cycle.

### `task cleanup`

Stop session and remove task resources:

```bash
agvv task cleanup --task-id demo_task_1 [--db-path ./tasks.db] [--force]
```

Common use: cleanup after merge/close, or force cleanup when needed.

### `daemon run`

Run monitor loop once or continuously:

```bash
agvv daemon run [--db-path ./tasks.db] [--once] [--interval-seconds 30] [--max-loops 10] [--max-workers 1]
```

Common use: run `--once` in scripts, run loop mode in long-running automation.

## Task Spec: What Users Usually Need

Required fields:

- `project_name`
- `feature`
- `repo`

Very common fields:

- `task_id`: custom ID (auto-generated if omitted)
- `task_id` format: letters/numbers/`_`/`-` only
- `base_dir`: where project/worktrees live (default `~/code`)
- `from_branch`: starting branch (default `main`)
- `session`: tmux session name override (default `agvv-<task_id>`)
- `agent`:
  - `provider`: `codex` or `claude_code` (`claude` / `claude-code` also accepted)
  - `model`: optional model name
  - `extra_args`: optional list of args
- `agent_cmd`: optional full command override (if omitted, generated from provider/model/extra_args)
- `ticket`: optional external issue key stored in task context
- `params`: optional key-value map for task context metadata
- `create_dirs`: directories to pre-create in feature worktree
- `pr_title` / `pr_body`: PR content
- `task_doc`: file path used as PR body fallback
- `pr_base`: PR target branch (default equals `from_branch`)
- `branch_remote`: git remote for push (default `origin`)
- `commit_message`: custom finalization commit message
- `timeout_minutes`: timeout before task becomes `timed_out`
- `max_retry_cycles`: max auto retry cycles for PR feedback
- `auto_cleanup`: cleanup automatically after merge/close/timeout
- `keep_branch_on_cleanup`: keep feature branch after cleanup

## Recommended Skill Workflow

When this project is used as a skill, a practical workflow is:

1. Receive a task requirement.
2. Create a `task.json` spec.
3. Run `agvv task run`.
4. Schedule `agvv daemon run --once` (manually or through automation).
5. Check `agvv task status`.
6. Run `agvv task retry` or `agvv task cleanup` when needed.

## State Meanings (Simple)

- `pending`: task created, waiting to start
- `coding`: agent session is running or coding in progress
- `pr_open`: code pushed, PR open and being tracked
- `pr_merged`: PR merged
- `pr_closed`: PR closed without merge
- `timed_out`: task exceeded timeout
- `failed`: operation failed
- `cleaned`: resources cleaned
- `blocked`: manually or externally blocked

## Environment Variable

- `AGVV_DB_PATH`: default path for the task SQLite DB

## Troubleshooting

- `tmux not found`: install `tmux` first.
- `gh` command issues: run `gh auth login` and verify repo access.
- `Task id already exists`: change `task_id` or reuse existing task.
- `Feature worktree has uncommitted changes`: commit/stash or use `task cleanup --force`.
- `Unsupported agent provider`: use `codex` or `claude_code`.
