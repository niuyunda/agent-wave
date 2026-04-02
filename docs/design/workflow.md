# agvv Workflow

## End-to-End Flow

```text
tasks add (auto_manage=true) -> daemon auto runs implement
    -> completed (task status=done)
    -> failed (task status=failed)
```

## 1. Add a Task

The orchestrator prepares a `task.md` file:

```bash
agvv tasks add --project ~/projects/my-project --file task.md [--agent codex]
```

agvv auto-registers and initializes the project when needed, validates that the task name is unique, creates `.agvv/tasks/<name>/task.md`, and marks the task as `pending`.

If a task with the same name already exists, agvv rejects it.

`tasks add` always enables automatic orchestration (`auto_manage: true`) and ensures daemon is running. The daemon then picks this task up automatically and starts an `implement` run. If `--agent` is provided, that agent is used for the auto-run; otherwise project `default_agent` is used.

## 2. Daemon Executes the Run

Internally, agvv:

1. creates the task worktree if needed
2. ensures an acpx session exists for the task (idempotent)
3. runs the `before_run` hook
4. sends the prompt to the session (agent retains context from previous runs)
5. records runtime facts for monitoring
6. marks the task as `running`

## 3. Coding Agent Work

The coding agent works inside its dedicated task worktree. For `implement`/`repair`, the expected durable output is a new Git commit in that worktree.

agvv does not inspect content quality. It enforces mechanical completion artifacts only.

## 4. Run Completion

When the daemon sees that the coding-agent process has exited, it:

1. reads the exit code from the runtime sidecar when available
2. records the final run status
3. runs the `after_run` hook
4. updates the task state

Important rule:

- all purposes: successful process exit without a new checkpoint (vs. the run’s `base_commit`) is `failed`
- `review`: successful process exit without a non-empty report file is also `failed`

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
- failed result -> update/requeue task and let daemon run again
- timed out result -> inspect task feedback and adjust hooks/config

## 6. Merge

```bash
agvv tasks merge fix-login-bug
```

agvv:

1. checks out the main branch
2. merges the task branch
3. archives the task on success
4. removes the task worktree on success

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
- merge conflict: mark the task as `blocked`

The system stays small, but it should not lie about what is actually happening.
