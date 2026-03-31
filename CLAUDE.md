# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**agvv** is a deterministic project orchestration engine for AI coding agents. It's a pure CLI + daemon tool that manages state, worktrees, processes, and checkpoints for parallel coding work. It contains no LLM, no database, and no MCP — it acts as a control plane, not a decision-maker.

## Commands

```bash
# Install (editable)
uv pip install -e .

# Run tests
PYTHONPATH=src python -m unittest -v tests.test_robustness

# Run CLI
agvv --help
```

There is no configured linter or formatter.

## Architecture

### Three Core Concepts

1. **Task** — one unit of work, stored as `.agvv/tasks/<name>/task.md` with YAML frontmatter. Status: pending → running → done/failed/blocked. Each task gets branch `agvv/<task-name>`.
2. **Run** — one execution of a task (purpose: implement/test/review/repair). Stored as `.agvv/tasks/<name>/runs/NNN-<purpose>.md` with a runtime sidecar JSON tracking PIDs, timestamps, exit codes.
3. **Checkpoint** — a valid Git commit from the task worktree. For every run purpose, completion requires a **new** commit vs. the run’s recorded `base_commit`; exit 0 without that is failed. `review` runs also require a written report file.

### Runtime Model

```
User <-> Orchestrator Agent <-> agvv (CLI/daemon) <-> Coding Agents
```

Each task runs in its own git worktree (under `<project>/worktrees/<task-name>/`). Worktree lifecycle is internal — orchestrator never references worktrees directly.

### Source Layout

- `src/agvv/cli/` — Typer-based CLI. `main.py` is the entry point; subcommands in `*_cmd.py` files.
- `src/agvv/core/` — Business logic. `models.py` (Pydantic schemas), `task.py`, `run.py`, `checkpoint.py`, `worktree.py`, `agent_runner.py`, `config.py`, `project.py`.
- `src/agvv/daemon/server.py` — Background monitor: reconciles state from filesystem on restart, polls every 10s, detects timeouts/stalls.
- `src/agvv/utils/` — `git.py` (worktree/merge wrappers), `markdown.py` (frontmatter I/O), `format.py` (Rich output).

### Key Design Rules

- **Filesystem is truth.** No database. Daemon rebuilds state from disk on restart.
- **Strict checkpoint semantics.** A run is only "completed" if it produced a readable **new** Git commit (relative to `base_commit`) for its purpose; review runs must also produce the report artifact.
- **Process group tracking.** `agent_runner.py` spawns agents, writes sidecar JSON with launcher_pid/agent_pid/pgid. Termination escalates: cooperative cancel → SIGTERM → SIGKILL.
- **Hook lifecycle.** `before_run` failure aborts the run and cleans up a newly created worktree. `after_run` failure is logged but doesn't overwrite the run result.
- **Merge conflict → blocked.** Merge conflicts mark the task `blocked`; they are never silently resolved.
- **agvv decides nothing.** Priority, retry policy, output quality — all owned by the orchestrator, not agvv.

### Dependencies

typer (CLI), pydantic (validation), python-frontmatter (YAML frontmatter), rich (output formatting). Python >= 3.10.

## Tests

Tests focus on failure modes critical to a daemon-driven system: hook rollback, process stopping, child PID tracking, checkpoint failures, merge conflicts. They use a fake agent script and run end-to-end.
