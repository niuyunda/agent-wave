# Agent Wave (`agvv`)

`agvv` is a lightweight task orchestrator for coding agents.
It gives each task an isolated git worktree, runs the agent in a detached tmux session, and tracks lifecycle state in SQLite.

## What It Does

- Isolates task changes with `git worktree` (`main` + per-feature worktrees).
- Runs agent sessions in background `tmux` so work continues after terminal disconnect.
- Persists task state/events in SQLite (`pending`, `running`, `done`, `failed`, `timed_out`, `cleaned`).
- Provides operational commands: `task run/status/retry/cleanup` and `daemon run`.

## Requirements

- Python `>=3.10`
- `git`
- `tmux`
- A coding agent CLI in `PATH`:
  - `codex` (default)
  - `claude` (used when `--agent claude` or `--agent claude_code`)
- `uv` (recommended for install/run)

Agent provider note:

- `--agent claude` and `--agent claude_code` are equivalent inputs.
- Both normalize to the internal provider `claude_code` and invoke the `claude` CLI binary.

## Install

From PyPI:

```bash
uv tool install agent-wave
agvv --help
```

From source:

```bash
uv sync --dev
uv run agvv --help
```

## Quick Start

### 1) Create `task.md`

Write the detailed coding requirement in Markdown.

### 2) Create `task.json`

Minimal valid spec:

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "task_doc": "./task.md"
}
```

`task_doc` or `requirements` must be present (at least one).

### 3) Start a task

For an existing local repository:

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

For a new managed project (under current directory):

```bash
agvv task run --spec ./task.json
```

Use Claude Code instead of Codex:

```bash
agvv task run --spec ./task.json --agent claude
```

`--agent claude_code` is also valid and behaves the same as `--agent claude`.

### 4) Monitor and reconcile state

```bash
agvv task status
agvv daemon run --once
```

Run `daemon run --once` repeatedly to move states forward (`running -> done/timed_out`).

### 5) Retry or cleanup

Retry:

```bash
agvv task retry --task-id <task_id>
```

Force restart an existing tmux session during retry:

```bash
agvv task retry --task-id <task_id> --force-restart
```

Cleanup worktree resources:

```bash
agvv task cleanup --task-id <task_id>
```

Force cleanup even with dirty worktree:

```bash
agvv task cleanup --task-id <task_id> --force
```

## `task.json` Contract (CLI)

### Required fields

- `project_name`: `^[A-Za-z0-9_-]+$`
- `feature`: `^[A-Za-z0-9_-]+$`, and must not be `main` or `repo.git`
- One of:
  - `task_doc` (must end with `.md`)
  - `requirements` (non-empty string)

### Common optional fields

- `repo`: optional repository slug/identifier
- `from_branch`: base branch for feature worktree (default: `main`)
- `session`: custom tmux session name
- `ticket`: optional ticket identifier (for task metadata)
- `constraints`: list of extra constraints
- `timeout_minutes`: session timeout in minutes (default: `240`)
- `agent_extra_args`: extra args passed to the agent command

### Important runtime behavior

- `task_id` is generated at runtime; user-provided `task_id` is ignored.
- `agent`/`agent_model` in spec are reset by runtime; choose provider via CLI `--agent`.
- `base_dir` in spec is overridden by runtime:
  - no `--project-dir`: current working directory
  - with `--project-dir`: parent directory of that project

## CLI Summary

```bash
agvv task run --spec <path> [--db-path <path>] [--agent <codex|claude|claude_code>] [--agent-non-interactive|--agent-interactive] [--project-dir <path>]
agvv task status [--db-path <path>] [--task-id <id>] [--state <pending|running|done|failed|timed_out|cleaned>]
agvv task retry --task-id <id> [--db-path <path>] [--session <name>] [--force-restart]
agvv task cleanup --task-id <id> [--db-path <path>] [--force]
agvv daemon run [--db-path <path>] [--once] [--interval-seconds <n>] [--max-loops <n>] [--max-workers <n>]
```

## Data and Layout

- Default DB path: `~/.agvv/tasks.db`
- Override DB path with `--db-path` or environment variable `AGVV_DB_PATH`
- Managed project layout:

```text
<runtime_base>/<project_name>/
  repo.git/      # bare repository
  main/          # main worktree
  <feature>/     # feature worktree for one task
```

## Notes

- `daemon run --once` is required to reconcile background task state.
- `task cleanup` removes the feature worktree and deletes the feature branch in managed repo.
