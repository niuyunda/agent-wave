# agvv Architecture

## Runtime Model

agvv has two runtime pieces:

- CLI entrypoint (`agvv`)
- daemon monitor (`agvv daemon start`)

Top-level CLI surface is intentionally small:

- `agvv daemon`
- `agvv projects`
- `agvv tasks`
- `agvv feedback`

The repository still contains run/session/checkpoint modules under `src/agvv/core` and `src/agvv/cli`, but they are not mounted as top-level commands in `src/agvv/cli/main.py`.

Daemon state in memory is a cache only. Source of truth is persisted files.

## Persistent State

Per project:

```text
<project>/
├── worktrees/
│   └── <task>/
└── .agvv/
    ├── config.json
    ├── hooks/
    │   ├── after_create.sh
    │   ├── before_run.sh
    │   └── after_run.sh
    └── tasks/
        ├── <task>/
        │   ├── task.md
        │   └── runs/
        │       ├── 001-implement.md
        │       ├── 001-implement.runtime.json
        │       └── 001-implement.log
        └── archive/
            └── 2026-04-02-<task>/
```

Global:

```text
~/.agvv/
├── projects.json
├── daemon.pid
├── daemon.log
└── feedback.json
```

## Task Record

Input is markdown with YAML front matter:

```markdown
---
name: fix-login-bug
agent: codex
priority: high
---
```

Task rules:

- `name` is required
- `name` must match `[A-Za-z0-9._-]+`
- duplicate names are rejected across active and archived tasks in a project
- missing `status` defaults to `pending`
- provided `status` must be one of `pending/running/failed/blocked/done`
- missing `created_at` defaults to `YYYY-MM-DD`
- unknown front matter keys are preserved

Task branch name is derived as `agvv/<name>`.

## Run Record

Each run stores markdown front matter, for example:

```markdown
---
purpose: implement
agent: codex
status: running
started_at: 2026-04-02T10:00:00
finished_at:
checkpoint:
pid: 12345
launcher_pid: 12340
pgid: 12340
exit_code:
base_branch: agvv/fix-login-bug
base_commit: abc1234
report_path:
---
```

Sidecar runtime JSON (`*.runtime.json`) records live process facts used by daemon reconciliation.

Run log (`*.log`) keeps agent stdout/stderr tail for failure diagnostics.

## Worktree and Ref Strategy

- Implement/repair runs use branch-attached mode (`agvv/<task>`).
- Review/test runs use detached mode.
- Detached ref resolution:
1. `--base-branch` when provided
2. existing task branch (`agvv/<task>`) if present
3. main branch fallback

For implement/repair, `base_branch` can seed the task branch when branch does not exist yet.

## Session Model

Before prompting, agvv attempts to ensure an acpx session scoped by:

- agent
- worktree cwd
- task name

Session commands use preferred ordering first (`acpx --cwd ...`) and legacy ordering as fallback for compatibility.

## Hook Model

Project config `.agvv/config.json` can define:

- `hooks.after_create`
- `hooks.before_run`
- `hooks.after_run`

Behavior:

- `after_create`: only when worktree is first created
- `before_run`: every run; failure aborts run start and removes freshly created worktree
- `after_run`: best effort; does not overwrite run result on hook failure

## Completion Semantics

A run is considered successful only when mechanical artifacts are valid:

- exit code resolves to success
- checkpoint exists and differs from `base_commit`
- for `review`, `report_path` exists and is non-empty

Special notes:

- implement/repair can auto-commit dirty worktree changes via `agent_runner` on zero exit code
- failed/timed_out/stalled statuses mark task as `failed`
- stopped status marks task as `pending`
- completed status marks task as:
1. `done` when task has `auto_manage: true`
2. `pending` otherwise

## Daemon Monitoring

Daemon cycle scans registered projects and:

- auto-starts pending auto-managed tasks with no prior runs
- checks liveness of tracked agent PID
- times out long-running tasks (`DEFAULT_RUN_TIMEOUT`)
- reconciles stale `running` tasks on startup

Non-goals currently:

- no active stall detector enforcement (`DEFAULT_STALL_TIMEOUT` is defined but unused)
- no output quality scoring

## Merge Semantics

`agvv tasks merge` preconditions:

- project primary worktree must already be on main branch
- project primary worktree must be clean (ignoring `.agvv/` and `worktrees/`)

On success:

- merge task branch into main
- close latest session (best effort)
- remove worktree and delete branch (best effort)
- move task into archive with date prefix
- status becomes `done`

On conflict:

- merge is aborted
- task status becomes `blocked`
- conflicting files are surfaced in the error
