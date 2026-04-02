# agvv Overview

## Positioning

agvv is a deterministic orchestration engine for coding agents. It runs as a CLI plus a small background daemon and gives an orchestrator agent the mechanical capabilities needed for multi-project, multi-task parallel coding.

agvv does not contain an LLM and does not make judgment calls. It focuses on automatic task execution plus status visibility for orchestrators.

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

A task is one unit of work. The orchestrator provides a Markdown file with a unique `name` plus task content. agvv stores it under `.agvv/tasks/<name>/task.md`.

Task names must be unique within a project. The name is also used for the task branch name: `agvv/<task-name>`.

### Run

A run is one execution of a task. Each run has a `purpose`:

- `implement`
- `test`
- `review`
- `repair`

A task may have many runs over time.

### Checkpoint

A checkpoint is a Git commit read from the task worktree. In agvv, a run is only considered complete if that checkpoint is actually present and readable.

Completion rules are purpose-aware:

- Every run purpose must produce a **new** checkpoint commit relative to the run’s recorded `base_commit`.
- `review`: must also write a non-empty repository report file at `report_path`.

## Practical Boundaries

agvv is intentionally not:

- a scheduler with built-in prioritization beyond pending-task auto dispatch
- a queueing system
- a hosted service
- a web dashboard
- a workflow engine with arbitrary plugins

It is a local deterministic control plane for coding work.

## Runtime Compatibility Notes

- agvv appends a prompt hint to use `python3` when `python` is not available.
- This reduces environment-specific failures across Linux distributions and WSL setups.
