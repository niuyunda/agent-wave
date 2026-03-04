---
name: agent-wave
description: Agent execution skill for running coding tasks via `agvv` with isolated worktrees, tmux sessions, and runtime state reconciliation.
---

# Agent Wave Skill

Use this skill when you need to run or maintain coding tasks with `agvv`.

## Commands

Use only:

- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

From source checkout, use `uv run agvv ...`.

## Spec Contract (`task.json`)

Required:

- `project_name`
- `feature`
- `repo`

Recommended:

- `requirements`
- `constraints`
- `acceptance_criteria` (2-5 items when provided)
- `task_doc` (fallback for requirements/PR body)
- `pr_title`, `pr_body`, `pr_base`
- `branch_remote`

Runtime ignores these spec fields:

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

## Runtime Rules

- With `--project-dir`, runtime adopts that repo and uses its parent as `base_dir`.
- Without `--project-dir`, runtime initializes a new project under current working directory.
- Ensure remote exists in `<base_dir>/<project_name>/repo.git` before finalize/push.
- DoD must exist at `.agvv/dod_result.json` and contain pass statuses for all acceptance criteria.

## Minimal Procedure

1. Validate `task.json` required fields.
2. Run `agvv task run --spec <spec_path> [--project-dir <repo>]`.
3. Run `agvv task status`.
4. Run `agvv daemon run --once`.
5. If failed/review changes requested, run `agvv task retry --task-id <id>`.
6. When done, run `agvv task cleanup --task-id <id> [--force]`.

## Failure Policy

- Invalid spec: fix spec and rerun `task run`.
- Missing remote: configure remote in managed `repo.git`, then rerun.
- Missing DoD result: relaunch coding/retry and regenerate `.agvv/dod_result.json`.
- Never update DB rows manually.
