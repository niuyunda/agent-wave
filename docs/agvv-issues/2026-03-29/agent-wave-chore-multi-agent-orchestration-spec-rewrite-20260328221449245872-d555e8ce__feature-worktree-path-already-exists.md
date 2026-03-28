# `agvv task run` failed when the target feature worktree path already existed

## Trigger

Command:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run agvv task run --spec ./task.md --dir /home/yunda/projects/agent-wave
```

The task spec requested feature `chore/multi-agent-orchestration-spec-rewrite`.

## Observed Behavior

`agvv task run` created a task row and immediately marked it failed with:

```text
Failed to launch coding session: Feature worktree path already exists: /home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite
```

The repository already contained:

- an existing worktree at `/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite`
- an existing branch `chore/multi-agent-orchestration-spec-rewrite`

This forced manual inspection before work could continue.

## Expected Behavior

When the target feature branch or worktree path already exists, `agvv` should make the recovery choice explicit instead of failing as a generic launch error.

Reasonable behavior would be one of:

- fail fast before creating the task row and explain that the feature already exists
- offer an explicit "resume existing worktree" path
- print a targeted recovery message that names the exact branch and worktree to inspect

## Temporary Workaround

Inspect the existing git state manually:

```bash
git worktree list
git branch -v
```

Then resume work in the existing matching worktree instead of creating a new one.
