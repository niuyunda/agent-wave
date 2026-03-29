# `agvv task run` failed when creating a feature branch with a slash

## Trigger

Command:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run agvv task run --spec /tmp/task.md --db-path /tmp/agvv-tasks.db --dir /home/yunda/projects/agent-wave
```

Task spec front matter requested feature:

```text
chore/multi-agent-orchestration-spec-v2
```

## Observed Behavior

`agvv task run` created the task row and then failed during worktree setup with:

```text
Failed to launch coding session: Command failed: git -C /home/yunda/projects/agent-wave/.git worktree add -b chore/multi-agent-orchestration-spec-v2 /home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-v2 main
...
fatal: cannot lock ref 'refs/heads/chore/multi-agent-orchestration-spec-v2': unable to create directory for ./refs/heads/chore/multi-agent-orchestration-spec-v2
```

The repository did not already contain `.git/refs/heads/chore` or a conflicting branch name.

## Expected Behavior

`agvv` should successfully create slash-style feature branches, because the documented feature naming model allows values like:

```text
chore/<slug>
fix/<slug>
feat/<slug>
refactor/<slug>
```

If the current `git -C <repo>/.git worktree add -b <branch>` invocation has edge cases with slash-style refs, `agvv` should either:

- create the branch using a safer sequence before `git worktree add`, or
- fail with a targeted diagnostic that explains the branch-ref creation bug and recommended workaround

## Temporary Workaround

Create an isolated worktree manually using a flat branch name and continue the task there until `agvv` handles slash-style feature refs correctly.
