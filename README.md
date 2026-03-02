# Agent Wave (`agvv`)

Agent Wave is a Python CLI for running AI coding tasks in isolated Git worktrees with optional `tmux` orchestration.

It standardizes a project layout so each feature or task runs in its own branch/worktree, keeps `main` separate, and records task metadata/status in a registry.

## Why This Exists

When multiple coding tasks or agents run in parallel, it is easy to:

- overwrite unrelated changes,
- lose context about which run did what,
- run commands in the wrong branch,
- leave stale worktrees behind.

`agvv` gives a repeatable workflow to avoid that:

- project bootstrap (new or adopted repo),
- feature worktree creation with metadata,
- optional detached `tmux` task execution,
- task lifecycle updates (`running`, `failed`, `needs_changes`, `done`),
- cleanup of worktree and branch after merge.

## Core Concepts

### Project Layout

For a project named `<project>` under `<base_dir>`:

```text
<base_dir>/<project>/
  repo.git/        # bare repository (source of truth)
  main/            # integration worktree
  <feature>/       # per-feature worktree(s)
```

Feature runs also get context metadata:

```text
<base_dir>/<project>/<feature>/.agvv/context.json
```

### Task Registry

Orchestrated tasks are stored in a JSON registry (default global path):

```text
~/.agvv/tasks.json
```

You can override this with:

```bash
export AGVV_TASKS_PATH=/custom/path/tasks.json
```

Registry includes:

- `tasks[]` entries (id, status, feature, session, retries, history, etc.),
- `summary` aggregates (by status and by project),
- `updated_at` timestamp and schema `version`.

## Requirements

- Python `>=3.10`
- `git` available on `PATH`
- `tmux` available on `PATH` (only required for `agvv orch ...` and `agvv feat start`)
- `uv` for dependency management and running commands

## Installation

### Development Install (recommended)

```bash
uv sync --dev
```

Run CLI without global install:

```bash
uv run agvv --help
```

### Build Package

```bash
uv build
```

## Quick Start

### 1) Initialize or adopt a project

Create fresh project layout:

```bash
uv run agvv project init myproj --base-dir ~/Code
```

Adopt an existing Git repository:

```bash
uv run agvv project adopt /path/to/existing/repo myproj --base-dir ~/Code
```

### 2) Create a feature worktree

```bash
uv run agvv create worktree myproj feat-login \
  --base-dir ~/Code \
  --from-branch main \
  --agent codex \
  --task-id run-20260226-001 \
  --ticket APP-123 \
  --param model=gpt-5 \
  --param change_type=feature \
  --mkdir src \
  --mkdir tests/unit
```

This creates:

- feature branch/worktree at `~/Code/myproj/feat-login`,
- metadata file at `~/Code/myproj/feat-login/.agvv/context.json`.

### 3) Work and verify inside the feature worktree

```bash
cd ~/Code/myproj/feat-login
git status
```

### 4) Cleanup when done

Remove worktree and delete feature branch:

```bash
uv run agvv feat cleanup myproj feat-login --base-dir ~/Code
```

Keep branch while removing only worktree:

```bash
uv run agvv feat cleanup myproj feat-login --base-dir ~/Code --keep-branch
```

## One-Step Agent Run (`feat start`)

`feat start` combines:

1. feature worktree creation (`create worktree` behavior),
2. detached `tmux` session launch,
3. task registry creation with status `running`.

Example:

```bash
uv run agvv feat start myproj feat-login \
  --base-dir ~/Code \
  --agent codex \
  --agent-cmd "python -m pytest -q"
```

Notes:

- `--agent-cmd` is required.
- If `--task-id` is omitted, a timestamped one is generated.
- If `--session` is omitted, default is `<agent>-<feature>`.

## Orchestration Commands (`orch`)

### Spawn

Launch a detached `tmux` session for an existing feature worktree and register task:

```bash
uv run agvv orch spawn myproj feat-login \
  --base-dir ~/Code \
  --session codex-feat-login \
  --agent codex \
  --agent-cmd "make test"
```

### List

```bash
uv run agvv orch list myproj --base-dir ~/Code
```

### Nudge

Send command/message into running task session:

```bash
uv run agvv orch nudge myproj run-20260226-001 \
  --base-dir ~/Code \
  --message "please rerun failing tests"
```

### Sync

Reconcile task status with `tmux` session liveness:

```bash
uv run agvv orch sync myproj --base-dir ~/Code
```

If a `running` task's session no longer exists, it is marked `failed`.

### Retry

Relaunch a `failed` or `needs_changes` task:

```bash
uv run agvv orch retry myproj run-20260226-001 \
  --base-dir ~/Code \
  --max-retries 3
```

Optional override command:

```bash
uv run agvv orch retry myproj run-20260226-001 \
  --base-dir ~/Code \
  --max-retries 3 \
  --agent-cmd "uv run pytest -q"
```

### Feedback

Apply review outcome:

```bash
uv run agvv orch feedback myproj run-20260226-001 \
  --base-dir ~/Code \
  --result changes_requested \
  --note "Address edge case in parser"
```

Allowed `--result` values:

- `passed` -> marks task `done`
- `changes_requested` -> marks task `needs_changes`

### Complete

Mark task complete, optionally cleanup worktree/branch:

```bash
uv run agvv orch complete myproj run-20260226-001 \
  --base-dir ~/Code \
  --cleanup
```

Keep branch during cleanup:

```bash
uv run agvv orch complete myproj run-20260226-001 \
  --base-dir ~/Code \
  --cleanup \
  --keep-branch
```

## Command Groups and Aliases

- `project`
  - `init`
  - `adopt`
- `create`
  - `worktree`
- `feat` (alias: `feature`)
  - `start`
  - `cleanup`
- `orch` (alias: `orchestrate`)
  - `spawn`, `list`, `nudge`, `sync`, `retry`, `feedback`, `complete`

## Naming and Safety Rules

Project and feature names are validated:

- only letters, numbers, `_`, `-`,
- no path separators,
- no path traversal segments.

Feature names cannot be reserved names:

- `main`
- `repo.git`

`--mkdir` paths are restricted to safe relative segments only.

Cleanup safety:

- `feat cleanup` refuses to remove a worktree with uncommitted tracked/staged changes.

## Status Model

Supported task statuses:

- `queued`
- `running`
- `needs_changes`
- `failed`
- `done`

Task history appends an event record on create/update with timestamp and metadata.

## Error Handling

Operational failures raise `AgvvError` and are shown in CLI with non-zero exit code.

Typical causes:

- missing project layout (`project init`/`project adopt` not run),
- invalid `--param` format (must be `KEY=VALUE`),
- duplicate task IDs,
- missing `tmux`,
- missing or already-existing `tmux` session.

## Development

### Run Tests

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing --cov-report=xml
```

### Docstring Coverage Gate (100%)

Enable the local pre-commit hook once per clone:

```bash
git config core.hooksPath .githooks
```

On every `git commit`, the hook runs:

```bash
uv run interrogate agvv --fail-under=100 --quiet
```

`--fail-under=100` enforces docstring coverage to be 100%.

### Lint

```bash
uv run ruff check .
```

## CI

GitHub Actions workflow runs:

- lint (`ruff`) on Python 3.12,
- tests on Python 3.10/3.11/3.12 with coverage,
- package build after lint+test pass.

## Package Metadata

- package name: `agent-wave`
- CLI entrypoint: `agvv` (mapped to `agvv.cli:app`)
- build backend: `hatchling`
