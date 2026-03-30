# agvv

Deterministic project orchestration for coding agents.

agvv is a small CLI + daemon that gives an orchestrator agent the mechanical tools needed to run parallel coding work across multiple projects. It does not contain an LLM, scoring logic, retry policy, or product judgment. It only manages state, worktrees, processes, and checkpoints.

## Core Principles

- Codebase is truth. Persistent state lives in files under each repository's `.agvv/` directory.
- Checkpoint equals Git commit. A successful run must leave behind a valid commit that the next agent can continue from.
- Tool, not decider. agvv performs mechanical actions only. The orchestrator agent decides what to run next.
- Minimal surface area. The core concepts are Task, Run, and Checkpoint.

## Architecture

```text
User <-> Orchestrator Agent <-> agvv (CLI/daemon) <-> Coding Agents
```

agvv manages task state, worktree lifecycle, coding-agent processes, and checkpoint records. Each task runs in its own Git worktree, so multiple tasks can proceed in parallel.

## Installation

```bash
# Requires Python >= 3.10
pip install -e .

# Or with uv
uv pip install -e .
```

## Quick Start

### 1. Register a project

```bash
agvv project add ~/projects/my-app
```

This initializes a `.agvv/` directory inside the repository and adds the project to the global registry in `~/.agvv/projects.md`.

### 2. Add a task

Prepare a `task.md`:

```markdown
---
name: fix-login-bug
---

## Goal
Fix the white screen issue on the login page in Safari.

## Acceptance Criteria
- Login works on Safari 17
- Existing tests still pass
```

```bash
agvv task add --project ~/projects/my-app --file task.md
```

### 3. Start a run

```bash
agvv run start fix-login-bug --purpose=implement --agent=codex
# Review against an existing branch/ref
agvv run start review-login --purpose=review --agent=codex --base-branch=agvv/fix-login-bug
```

agvv creates or reuses the task worktree, runs lifecycle hooks, launches the coding agent, records runtime facts, and marks the task as `running`.

### 4. Check status

```bash
# Global overview
agvv project list

# Task list for one project
agvv task list --project ~/projects/my-app

# Full task details with run history
agvv task show fix-login-bug

# Checkpoint information for the latest run
agvv checkpoint show fix-login-bug
```

### 5. Merge

```bash
agvv task merge fix-login-bug
```

On success, agvv merges the task branch into the main branch, removes the worktree, and archives the task. On conflict, agvv aborts the merge, marks the task as `blocked`, and reports the conflicting files.

## CLI Reference

### `daemon`

```bash
agvv daemon start     # Start background monitoring
agvv daemon stop      # Stop the daemon
agvv daemon status    # Show daemon status
```

### `project`

```bash
agvv project add <path>      # Register a repository and initialize .agvv/
agvv project list            # Show registered projects with summary counts
agvv project remove <path>   # Remove from the registry only
```

### `task`

```bash
agvv task add --project <path> --file <task.md>
agvv task list [--project <path>]
agvv task show <task-name>
agvv task merge <task-name>
```

### `run`

```bash
agvv run start <task-name> --purpose=<purpose> --agent=<agent>
agvv run stop <task-name>
agvv run status [--project <path>]
```

`purpose`: `implement` | `test` | `review` | `repair`

`--base-branch` is recommended for `review`/`test` runs so they execute against an existing branch/ref instead of creating a new task branch.

### `checkpoint`

```bash
agvv checkpoint show <task-name>
```

### Global options

```bash
--project <path>    # Explicit project path for commands that need it
--json              # Structured output
```

## Workflow

```text
task add -> run(implement) -> checkpoint -> run(review/test)
    -> pass -> merge
    -> fail -> run(repair) -> checkpoint -> ...
```

Multiple tasks can run in parallel, each in its own worktree. agvv does not decide concurrency policy; it only exposes the current state so the orchestrator can decide.

## Process Model

agvv keeps monitoring simple but reliable:

- Each run is launched through a tiny Python runner.
- The runner records runtime facts in a sidecar JSON file next to the run record.
- The daemon monitors the real coding-agent child process, not just a transient launcher process.
- `agvv run stop` only marks a run as `stopped` after the underlying process group is actually gone.

This keeps the system small while avoiding false states such as "stopped but still running" or "launcher died but child is still alive".

## Completion Semantics

- `implement` and `repair` runs require a **new Git commit checkpoint** created during that run.
- Exit code `0` without a new checkpoint is downgraded to `failed` (`finish_reason=no_new_checkpoint`).
- `review` runs must write a report file in the repository (`reports/agvv/<task>/<run>-review.md`).
- `review` and `test` runs may complete without creating a new code commit.
- `agvv checkpoint show` does not hide latest failures; if the latest run has no checkpoint, it reports that explicitly and includes the previous checkpoint when available.

## Python Command Compatibility

- agvv appends runtime guidance to every run prompt: if `python` is unavailable, use `python3`.
- For local verification commands in this repo, prefer:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -v
```

## Project Structure

```text
src/agvv/
├── cli/           # Typer command groups
├── core/          # Task, run, checkpoint, and project logic
├── daemon/        # Background monitoring and reconciliation
└── utils/         # Git and Markdown helpers
```

## State Storage

```text
<project-repo>/
└── .agvv/
    ├── config.md
    └── tasks/
        ├── fix-login-bug/
        │   ├── task.md
        │   └── runs/
        │       ├── 001-implement.md
        │       ├── 001-implement.runtime.json
        │       └── 002-review.md
        └── archive/
            └── 2026-03-30-fix-login-bug/

~/.agvv/
├── projects.md
├── daemon.pid
└── daemon.log
```

`*.runtime.json` is a lightweight sidecar file that records runtime facts such as `launcher_pid`, `agent_pid`, `pgid`, `started_at`, `finished_at`, and `exit_code`.

## Testing

agvv now includes focused robustness tests for the failure modes that matter most in a daemon-driven orchestration tool:

- failed `before_run` hook rollback
- stopping an uncooperative run
- daemon tracking the real child process instead of a dead launcher
- successful exit without a valid checkpoint
- checkpoint display after a latest-run failure
- merge conflict handling and `blocked` task state

Run them with:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_robustness
```

The goal is not a huge testing pyramid. The goal is a small set of end-to-end fault-oriented tests that keep the core engine honest.

## License

MIT
