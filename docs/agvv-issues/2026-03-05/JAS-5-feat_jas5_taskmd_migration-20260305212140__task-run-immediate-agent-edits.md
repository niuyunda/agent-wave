# agvv issue record

- task_id: `JAS-5-feat_jas5_taskmd_migration-20260305212140`
- date: `2026-03-05`
- topic: `task-run-immediate-agent-edits`

## Trigger command/input

```bash
agvv task run --spec .agvv-local/jas-5/task.json --project-dir /home/yunda/projects/test/JAS-5 --db-path /home/yunda/projects/test/JAS-5/.agvv-local/jas-5/tasks.db --agent codex --agent-non-interactive
```

## Observed behavior

- `task run` immediately launched the coding agent in tmux and started writing code in the new feature worktree.
- During manual follow-up development, several files were already modified by the background session.
- In this sandbox, direct `tmux` inspection commands were inconsistent with `uv run`-invoked checks, which made session state harder to reason about.

## Expected behavior

- A predictable way to create/adopt worktree resources first, then explicitly start agent execution when ready.
- Session state checks should be consistent across supported invocation paths.

## Temporary workaround

- Reconciled task state with `agvv daemon run --once` / `agvv task status`.
- Avoided concurrent edits by proceeding only after ensuring deterministic local test validation.
