# agvv CLI Reference

## `daemon`

```bash
agvv daemon start
agvv daemon stop
agvv daemon status
```

Use the daemon to monitor active runs and reconcile stale state after restarts.

## `project`

```bash
agvv project add <path>
agvv project list
agvv project remove <path>
```

- `project add`: registers a repository and initializes `.agvv/`
- `project list`: shows registered projects and summary counts
- `project remove`: removes the project from the global registry only

## `task`

```bash
agvv task add --project <path> --file <task.md>
agvv task list [--project <path>]
agvv task show <task-name>
agvv task merge <task-name>
```

- `task add`: reads `name` from the task front matter and creates `.agvv/tasks/<name>/task.md`
- `task list`: lists tasks for one project or all registered projects
- `task show`: shows task metadata, latest status, and run history
- `task merge`: merges the task branch into the main branch and archives the task on success

If `task merge` hits a conflict, agvv aborts the merge, marks the task as `blocked`, and reports the conflict files.

## `run`

```bash
agvv run start <task-name> --purpose=<purpose> --agent=<agent> [--base-branch=<ref>]
agvv run stop <task-name>
agvv run status [--project <path>]
```

Purpose values:

- `implement`
- `test`
- `review`
- `repair`

Behavior notes:

- `run start` creates or reuses the task worktree
- `run start --base-branch` lets `review`/`test` run against an existing branch/ref
- `run stop` only succeeds if the underlying process group is actually stopped
- `run status` shows active runs across one project or all projects

## `session`

```bash
agvv session ensure <task-name> --agent <agent>
agvv session close <task-name> --agent <agent>
agvv session status <task-name> --agent <agent>
agvv session list --agent <agent>
```

- `session ensure`: idempotent creation of an acpx session for a task. The session is scoped to the task's worktree and named after the task. Called automatically by `run start`.
- `session close`: soft-close a session (keeps conversation history in acpx). Called automatically by `task merge`.
- `session status`: show session process status (PID, last activity, closed state).
- `session list`: list all sessions for a given agent type.

Sessions persist across runs, so the coding agent retains conversation context through the implement -> review -> repair cycle.

## `checkpoint`

```bash
agvv checkpoint show <task-name>
```

This shows the latest checkpoint context for a task. If the latest run has no checkpoint, agvv reports that directly and may include the previous checkpoint for reference.

Run completion rules:

- `implement` / `repair`: require a new checkpoint commit
- `review`: requires a review report file in repo (`reports/agvv/...`)
- `test`: exit code drives status; new commit is optional

## Status Model

agvv exposes state at three levels.

### Global project summary: `agvv project list`

Example:

```text
PROJECT                    TASKS  RUNNING  PENDING  DONE  FAILED
~/projects/my-app          5      2        1        1     1
~/projects/api-server      3      1        0        2     0
```

`FAILED` includes both `failed` and `blocked` tasks because both require orchestrator attention.

### Task list: `agvv task list --project <path>`

Example:

```text
TASK              STATUS    RUN#  PURPOSE     AGENT   DURATION  LAST EVENT
fix-login-bug     running   2     implement   codex   12m 30s   running
add-search        pending   4     review      claude  3m 10s    completed
refactor-auth     failed    3     test        codex   8m 45s    failed
deps-sync         blocked   5     repair      codex   -         merge conflict
```

Statuses:

- `pending`
- `running`
- `failed`
- `blocked`
- `done`

### Task detail: `agvv task show <task-name>`

Shows:

- task metadata
- current status
- run history
- latest checkpoint information when present

## Global Options

```bash
--project <path>
--json
```

`--json` is intended for machine-readable orchestration.
