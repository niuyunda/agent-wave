---
name: agent-wave
description: Agent execution skill for running coding tasks via `agvv` with isolated worktrees, tmux sessions, and runtime state reconciliation.
---

# Agent Wave Skill

## Purpose

Use this skill to execute coding tasks through `agvv` as an agent runtime primitive:

- isolate each task in a feature worktree
- launch coding in `tmux`
- track task lifecycle in SQLite
- reconcile PR-driven state transitions

This file defines **agent behavior**, not end-user documentation.

## Trigger Conditions

Use this skill when the task includes one or more of:

- "start/run a coding task"
- "track/reconcile task status"
- "retry failed task"
- "cleanup task resources"
- "operate multiple agent tasks consistently"

## Command Contract (Current And Valid)

Use only these commands:

- `agvv project init`
- `agvv project adopt`
- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

If running from source checkout (not tool-installed), use the `uv run agvv ...` form.

Do not use deprecated command groups such as `feature` or `orch`.

## Required Inputs

Before execution, ensure there is a task spec file (`.json` or `.yaml`) with at least:
YAML support requires PyYAML to be installed (for example `uv add pyyaml`); without it, `.yaml` specs can fail at runtime:

- `project_name`
- `feature`
- `repo`
- `base_dir`

Before `agvv task run`, ensure the managed project bare repo has the configured remote:

- default remote name: `origin`
- custom remote: `branch_remote` from spec
- setup example: `git -C <base_dir>/<project_name>/repo.git remote add <remote> <repo-url>`

Recommended fields:

- `task_id`
- `task_id` should only include letters/numbers/`_`/`-`
- `base_dir`
- `from_branch`
- `session`
- `agent.provider` (`codex` or `claude_code`)
- `agent.model`
- `agent.extra_args`
- `agent_cmd` (full command override when needed)
- `ticket`
- `params`
- `create_dirs`
- `pr_title`, `pr_body`
- `pr_base`, `branch_remote`
- `commit_message`
- `timeout_minutes`, `max_retry_cycles`
- `auto_cleanup`, `keep_branch_on_cleanup`

## Hard Rules

1. Never modify runtime DB rows directly.
2. Never bypass `agvv` lifecycle commands with ad-hoc manual state transitions.
3. Never run deprecated `agvv` subcommands.
4. Retry only through `agvv task retry`.
5. Clean up finished or abandoned tasks through `agvv task cleanup`.
6. Prefer explicit `task_id` in automation.
7. Always set explicit `base_dir`.
8. Never run `agvv task run` without a configured push remote for the target project repo.

## Execution Algorithm

1. **Validate Inputs**
   - Confirm spec file exists and is readable.
   - Confirm required fields exist.
   - Confirm project layout exists (`project init` or `project adopt` completed).
   - Confirm remote exists in `<base_dir>/<project_name>/repo.git` (default `origin` or `branch_remote`).
   - Confirm remote exists in `<base_dir>/<project_name>/repo.git` (default `origin` or `branch_remote`).

2. **Prepare Project (If Needed)**
   - Initialize or adopt repository layout:
   - `agvv project init <project_name> --base-dir <base_dir>` or
   - `agvv project adopt <project_name> --existing-repo <path> --base-dir <base_dir>`
   - Configure remote:
   - `git -C <base_dir>/<project_name>/repo.git remote add <remote> <repo-url>`

3. **Start Task**
   - Run:
   - `agvv task run --spec <spec_path> [--db-path <db_path>] [--agent <provider>]`

4. **Observe Status**
   - Run:
   - `agvv task status [--db-path <db_path>] [--task-id <task_id>] [--state <state>]`

5. **Reconcile State**
   - Single-pass automation default:
   - `agvv daemon run --once [--db-path <db_path>] [--max-workers <n>]`
   - Loop mode only when explicitly required:
   - `agvv daemon run --interval-seconds <sec> [--max-loops <n>]`

6. **Retry If Recoverable**
   - Run:
   - `agvv task retry --task-id <task_id> [--db-path <db_path>] [--session <session>]`

7. **Cleanup**
   - Normal:
   - `agvv task cleanup --task-id <task_id> [--db-path <db_path>]`
   - Force (only when necessary):
   - `agvv task cleanup --task-id <task_id> [--db-path <db_path>] --force`

## Failure Handling Policy

- If command fails due to invalid spec: fix spec and retry `task run`.
- If command fails with `No git remote '<name>' configured`: configure remote in managed `repo.git`, then re-run `task run`.
- If task is non-recoverable: do not force retry logic; report and stop.
- If cleanup fails because of local changes: prefer normal resolution, use `--force` only when requested or operationally required.
- If `gh`/`tmux` is unavailable: report dependency issue clearly.

## Output Contract For Agent Responses

When using this skill, the agent response should include:

1. action taken (exact command family used)
2. task id and current state (if available)
3. next recommended action (`status`, `daemon run --once`, `retry`, or `cleanup`)
4. blocking reason (if any)

## Minimal Reference

```bash
agvv task run --spec ./task.json
agvv task status --task-id <task_id>
agvv daemon run --once
agvv task retry --task-id <task_id>
agvv task cleanup --task-id <task_id>
```
