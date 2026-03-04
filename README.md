# Agent Wave (`agvv`)

[中文文档 (README.zh-CN.md)](./README.zh-CN.md)

`agvv` runs coding tasks in isolated git worktrees and tracks task state with SQLite.

## What You Need

- Python `>=3.10`
- `git`, `tmux`, `gh` (authenticated)
- `uv`

## Install

```bash
uv tool install agvv
agvv --help
```

From source:

```bash
uv sync --dev
uv run agvv --help
```

## Quick Start

### 1) Write `task.json` (core metadata only)

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "task_doc": "./task.md",
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo"
}
```

### 2) Start task

Existing local repo:

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

Create new managed project under current directory:

```bash
agvv task run --spec ./task.json
```

### 3) Monitor and reconcile

```bash
agvv task status
agvv daemon run --once
```

## Common Commands

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--agent-non-interactive/--agent-interactive] [--project-dir /path/to/repo]
agvv task status [--db-path ./tasks.db] [--task-id <task_id>] [--state coding]
agvv task retry --task-id <task_id> [--db-path ./tasks.db] [--session custom-session] [--force-restart]
agvv task cleanup --task-id <task_id> [--db-path ./tasks.db] [--force]
agvv daemon run [--db-path ./tasks.db] [--once] [--interval-seconds 30] [--max-loops 10] [--max-workers 1]
```

## `task.json` Rules

Required:

- `project_name`
- `feature`
- `repo`

Required:

- `task_doc` (mandatory Markdown `.md`; put detailed requirements/constraints/acceptance criteria here)

Recommended:

- `pr_title`, `pr_body`, `pr_base`
- `branch_remote` (default: `origin`)

Ignored at runtime (do not rely on these in spec):

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

Notes:

- Keep `task.json` minimal (core identifiers and workflow metadata only).
- Put detailed development instructions into `task_doc` instead of `requirements`/`constraints` fields.
- `task_doc` is required and must end with `.md`.
- `acceptance_criteria` must be 2-5 items when provided.
- If omitted, runtime injects a stable default 2-item checklist.
- `base_dir` is resolved at runtime:
  - with `--project-dir`: parent directory of that path
  - without `--project-dir`: current working directory

## Artifacts Written In Worktree

`agvv` writes these files under `.agvv/`:

- `input_snapshot.json`
- `rendered_prompt.md`
- `agent_output.log`
- `agent_output_summary.txt`
- `dod_result.json` (required before finalize)

## Troubleshooting

- `tmux not found`: install `tmux`.
- `gh` auth issues: run `gh auth login`.
- `No git remote 'origin' configured`: add remote to managed repo, e.g. `git -C <base_dir>/<project_name>/repo.git remote add origin <repo-url>`.
