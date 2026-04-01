# agvv Workflow

## End-to-End Flow

```text
tasks add -> runs(implement) -> checkpoints -> runs(review/test)
    -> pass -> merge
    -> fail -> runs(repair) -> checkpoints -> runs(review/test) -> ...
```

## 1. Add a Task

The orchestrator prepares a `task.md` file:

```bash
agvv tasks add --project ~/projects/my-project --file task.md
```

agvv auto-registers and initializes the project when needed, validates that the task name is unique, creates `.agvv/tasks/<name>/task.md`, and marks the task as `pending`.

If a task with the same name already exists, agvv rejects it.

## 2. Start a Run

```bash
agvv runs start fix-login-bug --purpose=implement --agent=codex
```

Internally, agvv:

1. creates the task worktree if needed
2. ensures an acpx session exists for the task (idempotent)
3. runs the `before_run` hook
4. sends the prompt to the session (agent retains context from previous runs)
5. records runtime facts for monitoring
6. marks the task as `running`

For `review` and `test`, you can target an existing branch/ref:

```bash
agvv runs start review-login --purpose=review --agent=codex --base-branch=agvv/fix-login-bug
```

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

The orchestrator can inspect the latest result:

```bash
agvv checkpoints show fix-login-bug
```

Typical next actions:

- good result -> run `review` or `test`
- failed result -> run `repair`, retry with a different agent, or stop
- timed out result -> retry or adjust parameters

## 6. Review or Test

```bash
agvv runs start fix-login-bug --purpose=review --agent=claude
agvv runs start fix-login-bug --purpose=test --agent=codex
```

These runs reuse the same task worktree and session for the task. If `--base-branch` is provided, agvv attaches review/test work to that existing branch/ref in detached mode.

## 7. Merge

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

agvv runs start add-search --purpose=implement --agent=claude
agvv runs start add-dark-mode --purpose=implement --agent=pi
agvv runs start fix-login-bug --purpose=implement --agent=codex
```

Each task has its own worktree and branch. agvv does not serialize them unless the orchestrator chooses to.

## Failure Handling

agvv is designed to be strict about observable failures:

- failed `before_run` hook: abort the run and clean up a newly created worktree
- uncooperative `runs stop`: escalate from cooperative cancel to killing the process group
- dead launcher but live child process: keep the run as `running`
- successful exit but missing checkpoint: mark the run as `failed`
- merge conflict: mark the task as `blocked`

The system stays small, but it should not lie about what is actually happening.
