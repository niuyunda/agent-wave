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

Naming constraints (critical):

- `feature` is used as both branch/worktree directory name.
- Use slug format only: letters, numbers, hyphens, underscores (`[A-Za-z0-9_-]+`).
- Do **not** use spaces, natural-language sentences, slashes, or punctuation.
- Good: `python-calculator-cli`, `fix_login_bug`, `feat_calc_v2`
- Bad: `Create a Python calculator project`, `feature/calc`, `calc!`

Recommended (core metadata only):

- `task_doc` (mandatory; must be a Markdown file path ending with `.md`)
- `pr_title`, `pr_body`, `pr_base`
- `branch_remote`

Runtime ignores these spec fields:

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

Spec authoring policy:

- Keep `task.json` minimal: only core task identifiers/metadata.
- Do not put detailed development instructions in `requirements`, `constraints`, or `acceptance_criteria` fields.
- Put full task details in `task_doc` instead.
- `task_doc` format is mandatory Markdown (`.md`) only; plain text or other formats are not allowed.

## Runtime Rules

- With `--project-dir`, runtime adopts that repo and uses its parent as `base_dir`.
- Without `--project-dir`, runtime initializes a new project under current working directory.
- Ensure remote exists in `<base_dir>/<project_name>/repo.git` before finalize/push.
- DoD must exist at `.agvv/dod_result.json` and contain pass statuses for all acceptance criteria.

## Minimal Procedure

1. Validate `task.json` required fields and naming constraints.
   - Especially verify `feature` uses slug format (`[A-Za-z0-9_-]+`).
   - Ensure detailed task description is in `task_doc` (not in `requirements`/`constraints`).
   - Reject spec if `task_doc` is missing or does not end with `.md`.
2. Run `agvv task run --spec <spec_path> [--project-dir <repo>]`.
3. Run `agvv task status`.
4. Run `agvv daemon run --once`.
5. If failed/review changes requested, run `agvv task retry --task-id <id>`.
6. When done, run `agvv task cleanup --task-id <id> [--force]`.

## Failure Policy

- Invalid spec: fix spec and rerun `task run`.
- Invalid `feature` name: convert to slug and rerun (example: `Create a Python calculator project` -> `python-calculator-project`).
- Missing remote: configure remote in managed `repo.git`, then rerun.
- Missing DoD result: relaunch coding/retry and regenerate `.agvv/dod_result.json`.
- Never update DB rows manually.
