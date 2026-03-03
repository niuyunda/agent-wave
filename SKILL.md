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

- `uv run agvv task run`
- `uv run agvv task status`
- `uv run agvv task retry`
- `uv run agvv task cleanup`
- `uv run agvv daemon run`

Do not use deprecated command groups such as `project`, `feature`, or `orch`.

## Required Inputs

Before execution, ensure there is a task spec file (`.json` or `.yaml`) with at least:
YAML support requires PyYAML to be installed (for example `uv add pyyaml` or `pip install pyyaml`); without it, `.yaml` specs can fail at runtime:

- `project_name`
- `feature`
- `repo`

Recommended fields:

- `task_id`
- `base_dir`
- `from_branch`
- `agent.provider` (`codex` or `claude_code`)
- `agent.model`
- `agent.extra_args`
- `create_dirs`
- `pr_title`, `pr_body`
- `timeout_minutes`, `max_retry_cycles`
- `auto_cleanup`, `keep_branch_on_cleanup`

## Hard Rules

1. Never modify runtime DB rows directly.
2. Never bypass `agvv` lifecycle commands with ad-hoc manual state transitions.
3. Never run deprecated `agvv` subcommands.
4. Retry only through `agvv task retry`.
5. Clean up finished or abandoned tasks through `agvv task cleanup`.
6. Prefer explicit `task_id` in automation.
7. Use explicit `base_dir` in automation contexts.

## Execution Algorithm

1. **Validate Inputs**
   - Confirm spec file exists and is readable.
   - Confirm required fields exist.

2. **Start Task**
   - Run:
   - `uv run agvv task run --spec <spec_path> [--db-path <db_path>] [--agent <provider>] [--model <model>]`

3. **Observe Status**
   - Run:
   - `uv run agvv task status [--db-path <db_path>] [--task-id <task_id>] [--state <state>]`

4. **Reconcile State**
   - Single-pass automation default:
   - `uv run agvv daemon run --once [--db-path <db_path>] [--max-workers <n>]`
   - Loop mode only when explicitly required:
   - `uv run agvv daemon run --interval-seconds <sec> [--max-loops <n>]`

5. **Retry If Recoverable**
   - Run:
   - `uv run agvv task retry --task-id <task_id> [--db-path <db_path>] [--session <session>]`

6. **Cleanup**
   - Normal:
   - `uv run agvv task cleanup --task-id <task_id> [--db-path <db_path>]`
   - Force (only when necessary):
   - `uv run agvv task cleanup --task-id <task_id> [--db-path <db_path>] --force`

## Failure Handling Policy

- If command fails due to invalid spec: fix spec and retry `task run`.
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
uv run agvv task run --spec ./task.json
uv run agvv task status --task-id <task_id>
uv run agvv daemon run --once
uv run agvv task retry --task-id <task_id>
uv run agvv task cleanup --task-id <task_id>
```
