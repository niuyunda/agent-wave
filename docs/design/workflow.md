# agvv Workflow

## End-to-End Flow

```text
tasks add (auto_manage=true) -> daemon auto runs implement
    -> completed (auto-managed task status=done)
    -> failed/timed_out (task status=failed)
```

## 1. Add a Task

The orchestrator prepares a `task.md` file:

```bash
agvv tasks add --project ~/projects/my-project --file task.md [--agent codex]
```

agvv auto-registers and initializes the project when needed, validates task name and uniqueness, creates `.agvv/tasks/<name>/task.md`, and marks task `pending`.

If a task with the same name already exists, agvv rejects it.

`tasks add` always enables automatic orchestration (`auto_manage: true`) and sets feedback fields (`queued`). It starts daemon automatically unless `AGVV_SKIP_DAEMON_AUTOSTART` is truthy.

Daemon pickup starts `implement` run when task has no existing runs. Agent selection order is:

1. task `agent` field (`--agent` on `tasks add` overrides source markdown)
2. project `default_agent`
3. fallback `claude`

## 2. Daemon Executes the Run

Internally, agvv:

1. creates the task worktree if needed
2. ensures an acpx session exists for the task (idempotent)
3. runs the `before_run` hook
4. sends the prompt to the session (agent retains context from previous runs)
5. records runtime facts for monitoring
6. marks the task as `running`

## 3. Coding Agent Work

The coding agent works inside task worktree `<project>/worktrees/<task>`.

- `implement`/`repair`: branch-attached mode (`agvv/<task>`)
- `review`/`test`: detached mode at resolved ref (`--base-branch`, else task branch if exists, else main)

agvv does not inspect output quality. It enforces mechanical completion artifacts only.

## 4. Run Completion

When the daemon sees that the coding-agent process has exited, it:

1. reads the exit code from the runtime sidecar when available
2. records the final run status
3. runs the `after_run` hook
4. updates the task state

Important rule:

- all purposes: successful process exit without a new checkpoint (vs. the run’s `base_commit`) is `failed`
- `review`: successful process exit without a non-empty report file is also `failed`
- `implement`/`repair`: helper runner may auto-commit dirty changes before final status is written

By default, review reports are expected at:

```text
reports/agvv/<task-name>/<run-number>-review.md
```

## 5. Inspect the Result

The orchestrator can inspect global/project/task status:

```bash
agvv projects
agvv projects show ~/projects/my-project
agvv tasks show fix-login-bug --project ~/projects/my-project
```

Typical next actions:

- good result -> merge
- failed result -> inspect feedback + logs, then update/requeue task
- timed out result -> inspect task feedback and adjust hooks/config

## 6. Merge

```bash
agvv tasks merge fix-login-bug --project ~/projects/my-project
```

agvv:

1. requires project primary worktree is on main branch and clean
2. merges the task branch
3. closes the latest task session (best effort)
4. archives task on success (`status=done`)
5. removes task worktree and branch (best effort)

If the merge conflicts:

- agvv aborts the merge
- the task becomes `blocked`
- the conflicting files are reported back to the orchestrator

## Parallel Work

Multiple tasks can run at the same time:

```bash
agvv tasks add --project ~/projects/my-app --file add-search.md
agvv tasks add --project ~/projects/my-app --file add-dark-mode.md
agvv tasks add --project ~/projects/my-app --file fix-login-bug.md
```

Each task has its own worktree and branch. agvv does not serialize them unless the orchestrator chooses to.

## Failure Handling

agvv is designed to be strict about observable failures:

- failed `before_run` hook: abort the run and clean up a newly created worktree
- dead launcher but live child process: keep the run as `running`
- successful exit but missing checkpoint: mark the run as `failed`
- successful review exit with checkpoint but missing report: mark the run as `failed`
- merge conflict: mark the task as `blocked`

The system stays small, but it should not lie about what is actually happening.
