# agvv Architecture

## Runtime Model

agvv has two parts:

- a CLI used by the orchestrator agent
- a background daemon that reconciles and monitors active runs

```bash
agvv daemon start
agvv daemon stop
agvv daemon status
```

The daemon's in-memory view is only a cache. The source of truth is always the filesystem inside each repository's `.agvv/` directory. After a restart, the daemon rebuilds state from files.

## Persistent State

All project-level state lives inside the repository:

```text
my-project/
├── src/
├── .agvv/
│   ├── config.md
│   └── tasks/
│       ├── fix-login-bug/
│       │   ├── task.md
│       │   └── runs/
│       │       ├── 001-implement.md
│       │       └── 001-implement.runtime.json
│       └── archive/
│           └── 2026-03-30-fix-login-bug/
└── package.json
```

Global state stays in the user's home directory:

```text
~/.agvv/
├── projects.md
├── daemon.pid
└── daemon.log
```

## Task Record

The orchestrator submits a Markdown file with a `name` and task body:

```markdown
---
name: fix-login-bug
---

## Goal
Fix the white screen issue on the login page in Safari.

## Context
Users report a white screen after clicking the login button in Safari 17.

## Acceptance Criteria
- Login works in Safari 17
- Existing tests still pass
```

agvv validates the name, creates `.agvv/tasks/fix-login-bug/`, and adds managed fields:

```markdown
---
name: fix-login-bug
status: pending
created_at: 2026-03-30
---
```

Rules:

- `name` is supplied by the orchestrator and must be unique per project
- `status` and `created_at` are managed by agvv
- the name is also used to derive the Git branch `agvv/<name>`

## Run Record

Each run gets a Markdown record:

```markdown
---
purpose: implement
agent: codex
status: completed
started_at: 2026-03-30T10:00:00
finished_at: 2026-03-30T10:15:00
checkpoint: abc1234
pid: 12345
launcher_pid: 12340
pgid: 12340
exit_code: 0
base_branch: agvv/fix-login-bug
base_commit: abc1234
report_path: reports/agvv/review-login/002-review.md
---
```

The run body is reserved for result text or structured summaries produced during the run.

## Runtime Sidecar

Each run may also have a sidecar JSON file:

```text
.agvv/tasks/fix-login-bug/runs/001-implement.runtime.json
```

It stores runtime facts needed for monitoring:

- `launcher_pid`
- `agent_pid`
- `pgid`
- `started_at`
- `finished_at`
- `exit_code`
- `status`

This file exists so the daemon can reason about the real coding-agent child process instead of a transient launcher process.

## Session Lifecycle

Each task has an associated acpx session. The session is a persistent agent context that retains conversation history across runs.

- `agvv run start` ensures a session exists before sending the prompt
- subsequent runs for the same task reuse the same session (the agent has context from previous runs)
- `agvv task merge` closes the session alongside worktree cleanup
- sessions can be managed explicitly with `agvv session ensure/close/status/list`

agvv delegates session state entirely to acpx. Session data is stored at `~/.acpx/sessions/` and is not duplicated inside `.agvv/`.

The session is scoped by `(agent, worktree cwd, task name)`. The agent process uses a queue-owner pattern: a background process per session handles prompts via IPC, and exits after an idle TTL.

## Worktree Lifecycle

Worktrees are an internal implementation detail. The orchestrator never has to manage them directly.

- `agvv run start` creates the worktree if needed
- the same task reuses the same worktree across runs
- `review`/`test` may target an existing branch/ref with `--base-branch` (detached mode)
- `agvv task merge` removes the worktree on success
- task archive or cleanup also removes the worktree when possible

## Hooks

Project-level hooks can be configured in `.agvv/config.md`:

```yaml
hooks:
  after_create: "./scripts/bootstrap.sh"
  before_run: "./scripts/pre-check.sh"
  after_run: "./scripts/cleanup.sh"
```

Hook semantics:

- `after_create`: runs after the worktree is first created
- `before_run`: runs before each run; if it fails, the run is aborted
- `after_run`: runs after each run; failures are logged but do not overwrite the run result

## Monitoring

The daemon continuously scans registered projects and checks active tasks.

Current monitoring responsibilities:

- detect dead processes
- detect timeout
- reconcile stale `running` state after daemon restart

Completion policy is enforced when a run exits:

- `implement` / `repair`: must produce a new commit checkpoint
- `review`: must produce a repository review report artifact

Current non-goals:

- no full stall detector yet
- no output-based progress scoring

This is intentional. agvv keeps monitoring minimal and grounded in observable facts.

## Reconciliation

When the daemon starts, it rebuilds the real state:

- scan all registered projects
- find tasks marked `running`
- read the latest run record and runtime sidecar
- if the tracked process is already dead, finish the run using the recorded exit code when available

This keeps daemon restarts cheap and safe.

## Merge Semantics

`agvv task merge` checks out the main branch and merges the task branch.

- on success: the task is archived and the worktree is removed
- on conflict: the merge is aborted, the task is marked `blocked`, and the conflicting files are reported

This makes merge conflict a visible orchestration event rather than a hidden Git detail.
