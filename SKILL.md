---
name: agent-wave
description: Deterministic SOP for AI agents using the agvv CLI safely.
---

# Agent Wave (`agvv`) Skill Instructions

Use this SOP when you execute coding tasks via `agvv`.
Follow it exactly to avoid invalid specs, broken sessions, or stuck task states.

## 1) Supported Commands

Use only these commands (from installed binary or source tree):

```bash
agvv task run --spec <path> [--db-path <path>] [--agent <provider>] [--agent-non-interactive|--agent-interactive] [--project-dir <path>]
agvv task status [--db-path <path>] [--task-id <id>] [--state <pending|running|done|failed|timed_out|cleaned>]
agvv task retry --task-id <id> [--db-path <path>] [--session <name>] [--force-restart]
agvv task cleanup --task-id <id> [--db-path <path>] [--force]
agvv daemon run --once [--db-path <path>] [--max-workers <n>]
```

If running from source, prefix with `uv run`:

```bash
uv run agvv ...
```

## 2) Input Files You Must Prepare

Create two files:

- `task.md`: full natural-language requirement
- `task.json`: structured metadata

### `task.json` minimum valid template

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "task_doc": "./task.md"
}
```

### Validation rules (strict)

- `project_name` must match: `^[A-Za-z0-9_-]+$`
- `feature` must match: `^[A-Za-z0-9_-]+$`
- `feature` cannot be `main` or `repo.git`
- At least one of these must be present:
  - `task_doc` (must end with `.md`)
  - `requirements` (non-empty string)

### Optional fields you can use

- `repo` (string)
- `from_branch` (default `main`)
- `session` (custom tmux session name)
- `ticket`
- `constraints` (string list)
- `timeout_minutes` (int, default `240`)
- `agent_extra_args` (string list)

### Runtime behavior you must know

- `task_id` in spec is ignored; runtime generates it.
- `agent` and `agent_model` in spec are reset by runtime.
- To select provider, use CLI `--agent` (`codex` default; `claude` and `claude_code` are equivalent inputs).
- When `task run` executes, `base_dir` from spec is overridden by runtime.

## 3) Execution Protocol

1. Validate files and naming rules.
2. Decide run mode:
   - Existing repo: use `--project-dir /abs/path/to/repo`
   - New managed project: do not pass `--project-dir`
3. Start task:

```bash
agvv task run --spec ./task.json [--project-dir ...] [--agent codex|claude]
```

4. Record the `task_id` from command output.
5. Poll until terminal state:

```bash
agvv task status --task-id <task_id>
agvv daemon run --once
```

Repeat step 5 until state is one of: `done`, `failed`, `timed_out`, `cleaned`.

6. If state is `failed` or `timed_out`:
   - Inspect `last_error` from `task status`
   - Fix root cause
   - Retry:

```bash
agvv task retry --task-id <task_id>
```

   - If a stale running tmux session exists, use:

```bash
agvv task retry --task-id <task_id> --force-restart
```

7. After user confirms completion, cleanup resources:

```bash
agvv task cleanup --task-id <task_id>
```

If cleanup is blocked by uncommitted changes in feature worktree, use `--force`.

## 4) Guardrails

- For `feature` and `project_name`, do not use spaces, slashes, or punctuation except underscore (`_`) and hyphen (`-`).
- Never use non-Markdown `task_doc` paths.
- Do not rely on spec-level `agent` fields for provider selection.
- Always run `daemon run --once`; without it, background state may not advance.
- Do not manually delete managed worktrees; use `task cleanup`.
