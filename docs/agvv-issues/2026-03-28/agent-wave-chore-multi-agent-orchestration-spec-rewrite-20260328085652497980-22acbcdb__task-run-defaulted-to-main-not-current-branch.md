# `agvv task run` defaulted to repo `main` instead of the current working branch

## Trigger

Command:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run agvv task run --spec ./task.md --dir /home/yunda/projects/agent-wave
```

Task spec front matter did not set `from_branch`, and the repository's current branch was `update-docs`.

## Observed Behavior

`agvv` created the isolated worktree branch from repository `main`, not from the currently checked-out `update-docs` branch.

As a result, the new worktree did not contain the current version of `docs/multi-agent-orchestration-spec.md`. I had to manually fast-forward the task worktree branch onto `update-docs` before editing the target file.

## Expected Behavior

The default behavior should make branch selection obvious and safe for documentation or feature work that begins from a non-`main` branch.

Reasonable options:

- default to the current checked-out branch when `--project-dir` points at an existing repo and `from_branch` is omitted, or
- fail fast with an explicit warning that the default base is `main`, or
- print the selected base branch prominently before creating the worktree

## Temporary Workaround

Fast-forward the task branch manually after worktree creation:

```bash
git merge --ff-only update-docs
```
