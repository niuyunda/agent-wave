# agvv

Deterministic project orchestration for coding agents.

agvv is a small CLI + daemon that gives an orchestrator agent the mechanical tools needed to run parallel coding work across multiple projects. It does not contain an LLM, scoring logic, retry policy, or product judgment. It only manages state, worktrees, processes, and checkpoints.

## Core Principles

- Codebase is truth. Persistent state lives in files under each repository's `.agvv/` directory.
- Checkpoint equals Git commit. A successful run must leave behind a valid commit that the next agent can continue from.
- Tool, not decider. agvv performs mechanical actions only. The orchestrator agent decides what to create, inspect, and merge next.
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

### 1. Add a task

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
agvv tasks add --project ~/projects/my-app --file task.md [--agent codex]
```

`tasks add` automatically initializes `.agvv/` metadata and registers the project in `~/.agvv/projects.json` when needed.

### 2. Automatic orchestration

`tasks add` queues the task for daemon execution (`implement` run) and ensures auto-orchestration is enabled for the task.
If `--agent` is provided, that value is stored on the task and used for daemon auto-runs (passed to `acpx`).

You can control daemon lifecycle explicitly when needed:

```bash
agvv daemons start
agvv daemons status
```

### 3. Check status

```bash
# All projects
agvv projects
# Alias
agvv projects list

# One project
agvv projects show ~/projects/my-app

# Tasks (all projects or one project)
agvv tasks
agvv tasks --project ~/projects/my-app
# Alias
agvv tasks list --project ~/projects/my-app

# One task
agvv tasks show fix-login-bug --project ~/projects/my-app
```

### 4. Merge

```bash
agvv tasks merge fix-login-bug
```

On success, agvv merges the task branch into the main branch, removes the worktree, and archives the task. On conflict, agvv aborts the merge, marks the task as `blocked`, and reports the conflicting files.

## CLI Reference

### `daemons`

```bash
agvv daemons start     # Start background monitoring
agvv daemons stop      # Stop the daemon
agvv daemons status    # Show daemon status
```

### `projects`

```bash
agvv projects                 # Show registered projects with summary counts
agvv projects list            # Alias of `agvv projects`
agvv projects show <path>     # One project with task statuses
agvv projects remove <path>   # Remove from the registry only
```

### `tasks`

```bash
agvv tasks add --project <path> --file <task.md> [--agent <name>]
agvv tasks [--project <path>]
agvv tasks list [--project <path>]   # Alias of `agvv tasks`
agvv tasks show <task-name>
agvv tasks merge <task-name>
```

### Global options

```bash
--project <path>    # Explicit project path for commands that need it
```

Output format: agvv command output is JSON by default (agent-friendly and machine-readable).

`projects list` and `tasks list` are compatibility aliases; `projects` and `tasks` are the primary entrypoints.

## Workflow

```text
tasks add -> daemon auto-runs implement -> projects/tasks query
    -> pass -> merge
    -> fail -> inspect feedback + retry by updating/requeueing task
```

Multiple tasks can run in parallel, each in its own worktree. agvv does not decide concurrency policy; it only exposes the current state so the orchestrator can decide.

## Process Model

agvv keeps monitoring simple but reliable:

- Each run is launched through a tiny Python runner.
- The runner records runtime facts in a sidecar JSON file next to the run record.
- The daemon monitors the real coding-agent child process, not just a transient launcher process.

This keeps the system small while avoiding false states such as "launcher died but child is still alive".

## Completion Semantics

- Every run purpose must create a **new Git commit checkpoint** during that run (vs. the recorded `base_commit`); exit code `0` without that is `failed` (`finish_reason=no_new_checkpoint`).
- `review` runs must also write a non-empty report file (default `reports/agvv/<task>/<run>-review.md`).
- `agvv tasks show` and `agvv projects show` surface latest run/feedback fields for failure inspection.

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
    ├── config.json
    ├── hooks/
    │   ├── after_create.sh
    │   ├── before_run.sh
    │   └── after_run.sh
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
├── projects.json
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
