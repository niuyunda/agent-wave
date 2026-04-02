# agvv Overview

## Positioning

agvv is a deterministic orchestration engine for coding agents. It is a local CLI plus daemon that handles task metadata, worktree/process lifecycle, and Git checkpoint tracking across repositories.

agvv does not include an LLM and does not make quality/product decisions. It focuses on mechanical run control and status visibility for an external orchestrator.

## Core Principles

**Codebase is truth**. There is no database. Persistent state lives in files under each repository's `.agvv/` directory.

**Checkpoint equals Git commit**. Meaningful work output must be captured as a commit so another agent can continue directly from the repository.

**Tool, not decider**. agvv creates worktrees, launches processes, records status, and detects failures. It does not decide priority, retry policy, or whether an output is good enough.

**Minimal design**. agvv keeps the model intentionally small: Task, Run, and Checkpoint.

## Roles

```text
User
  <-> conversation
Orchestrator Agent
  - interprets user intent
  - creates tasks
  - reads state and reacts to failures
  - decides merge/cleanup actions
  <-> CLI
agvv
  - task state management
  - worktree lifecycle
  - coding-agent process management
  - automatic daemon scheduling
  - checkpoint recording
  - timeout detection
  - daemon reconciliation
  <-> subprocesses
Coding Agents
  - perform coding work inside task worktrees
  - leave behind commits and repository state
```

The orchestrator should care about projects, tasks, and outcomes. It should not need to care how worktrees are created or how background processes are monitored.

## Core Concepts

### Task

A task is one unit of work. The orchestrator provides markdown with front matter containing `name`. agvv stores it under `.agvv/tasks/<name>/task.md`.

Task names must match `[A-Za-z0-9._-]+` and be unique across active and archived tasks in the same project. The name is also used for branch `agvv/<task-name>`.

### Run

A run is one attempt of a task. Purpose values:

- `implement`
- `test`
- `review`
- `repair`

A task can have multiple runs over time. Runtime metadata is recorded in markdown plus a sidecar `.runtime.json`.

### Checkpoint

A checkpoint is a Git commit read from the task worktree. A run is only considered successful when completion artifacts are present and valid.

Completion rules are purpose-aware:

- Every run purpose must produce a **new** checkpoint commit relative to the run’s recorded `base_commit`.
- `review`: must also write a non-empty repository report file at `report_path`.

Note: implement/repair runs may get an automatic commit from `agent_runner` when the process exits `0` with dirty changes.

## Practical Boundaries

agvv is intentionally not:

- a scheduler with built-in prioritization beyond pending-task auto dispatch
- a queueing system
- a hosted service
- a web dashboard
- a workflow engine with arbitrary plugins

It is a local deterministic control plane for coding work.

## Runtime Compatibility Notes

- agvv appends runtime prompt guidance: if `python` is unavailable, use `python3`.
- Top-level CLI intentionally exposes `daemon/projects/tasks/feedback` only; additional run/session/checkpoint internals remain code-level modules.
