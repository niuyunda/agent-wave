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
- A configured git remote for the managed project repo (default remote name: `origin`)

## Install And Check

```bash
uv tool install agvv
agvv --help
```

If you use this as a skill, make sure `agvv` is available in the environment where the agent runs.
For local development from source, use `uv sync --dev` and run CLI commands as `uv run agvv ...`.
Task specs are JSON only, and should focus on development requirements.

## 5-Minute Quick Start

### 1) Create a task spec file

Create `task.json`:

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "requirements": "Implement demo feature",
  "constraints": ["Do not change public API"],
  "acceptance_criteria": ["Relevant tests pass"],
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo",
  "pr_body": "Implement demo feature",
  "timeout_minutes": 240,
  "max_retry_cycles": 5,
  "auto_cleanup": true
}
```

### 2) Configure git remote (required)

Before `task run`, configure push remote for the managed bare repository:

```bash
git -C ./demo/repo.git remote add origin <repo-url>
```

Use the project path from your own `project_name`.
If your task uses a non-default remote name via `branch_remote`, configure that remote instead.

### 3) Start the task

```bash
agvv task run --spec ./task.json [--project-dir /path/to/existing/repo]
```

Expected output includes task id, state, and tmux session name.
If `--project-dir` is provided, Agent Wave auto-adopts that existing local project.
If omitted, Agent Wave auto-initializes a new managed project layout.

### 4) Check status

```bash
agvv task status
```

### 5) Reconcile once (daemon single pass)

```bash
agvv daemon run --once
```

This is the core loop for the skill: it checks active tasks and advances their state.

## Command Guide (User-Facing)

### `task run`

Create and launch one task from JSON spec:

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--project-dir /path/to/repo]
```

Common use: start new work with optional temporary agent provider override.
Behavior:
- with `--project-dir`: auto-adopt existing local project before launch.
- without `--project-dir`: auto-init a new managed project layout before launch.
- runtime ignores `task_id`, `agent*`, `agent_cmd`, and `from_branch` from spec.

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

- `task_id`: optional; runtime always generates and ignores this value from spec
- `base_dir`: optional; resolved automatically at runtime from CLI context
- `ticket`: optional external issue key stored in task context
- `requirements`: primary task requirement text (single source of truth for agent prompt)
- `constraints`: optional list of hard constraints for implementation
- `acceptance_criteria`: optional checklist used as task completion definition
- `params`: optional key-value map for task context metadata
- `create_dirs`: directories to pre-create in feature worktree
- `pr_title` / `pr_body`: PR content
- `task_doc`: optional requirement/description file path; used as fallback when `requirements` or `pr_body` is missing
- `pr_base`: PR target branch (default `main`)
- `branch_remote`: git remote for push (default `origin`)
- `commit_message`: custom finalization commit message
- `timeout_minutes`: timeout before task becomes `timed_out`
- `max_retry_cycles`: max auto retry cycles for PR feedback
- `auto_cleanup`: cleanup automatically after merge/close/timeout
- `keep_branch_on_cleanup`: keep feature branch after cleanup

DoD note:

- `acceptance_criteria` is machine-readable and must contain 2-5 items when provided.
- if omitted, runtime injects a stable default 2-item checklist.
- before PR finalization, agent must write `.agvv/dod_result.json` and mark each criterion as passing.

Ignored in spec at runtime:

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

Task launch also writes lightweight execution artifacts in feature worktree:

- `.agvv/input_snapshot.json`: resolved task inputs used for this run
- `.agvv/rendered_prompt.md`: final prompt passed to coding agent
- `.agvv/agent_output.log`: captured agent stdout/stderr
- `.agvv/agent_output_summary.txt`: latest output tail summary (written before finalization)
- `.agvv/dod_result.json`: agent-produced machine-readable DoD check result required for finalization

`base_dir` runtime resolution:

- with `--project-dir`: uses the parent directory of that path as `base_dir`
- without `--project-dir`: uses current working directory as `base_dir` and auto-creates `<cwd>/<project_name>/...`
- recommended practice: do not set `base_dir` in `task.json`

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
- `No git remote 'origin' configured`: configure remote first (for example, `git -C <managed-repo.git> remote add origin <repo-url>`), or set/use the remote from `branch_remote`.
- `Feature worktree has uncommitted changes`: commit/stash or use `task cleanup --force`.
- `Unsupported agent provider`: use `codex` or `claude_code`.
