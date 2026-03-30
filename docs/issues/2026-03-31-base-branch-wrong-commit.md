---
name: base-branch-worktree-wrong-commit
date: 2026-03-31
type: bug
severity: critical
status: open
reproduced: true
affects: repair
---

## Summary

`--base-branch` creates worktree at wrong base commit instead of the target branch's checkpoint.

## Environment

- agvv: current HEAD
- OS: WSL2

## Steps to Reproduce

```bash
# 1. Create implementation branch with a checkpoint
agvv run start impl-task --purpose implement --agent claude
# (agent creates commit b1b3743 on agvv/impl-task)

# 2. Try to repair based on that branch
agvv run start repair-task --purpose repair --agent claude --base-branch agvv/impl-task
```

## Expected Behavior

Worktree created with detached HEAD at `agvv/impl-task`'s checkpoint (`b1b3743`).

## Actual Behavior

Worktree created with detached HEAD at the project's initial/base commit (`ba2c77d`), not the checkpoint. The repair agent then commits to the wrong branch.

## Evidence

```
# worktree e2e-repair shows:
# HEAD at ba2c77d (old state)
# but agvv/e2e-calc has the repair commit (af050ba)
git worktree list:
  worktrees/e2e-repair  ba2c77d [agvv/e2e-repair]
  worktrees/e2e-calc    af050ba [agvv/e2e-calc]  # repair commit ended up here
```

## Root Cause

Likely in `worktree.py` — `start_run()` with `--base-branch` resolves the worktree base commit before the actual task branch checkpoint is available.

## Notes

Workaround: avoid `--base-branch` for repair tasks; instead merge the implementation branch first, then run repair against the merged branch.
