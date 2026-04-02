# agvv

Deterministic orchestration CLI for coding-agent workflows in local Git repositories.

`agvv` is a small file-backed control plane: it manages task state, worktrees, process lifecycle, and checkpoint recording. It does not make product decisions, prioritize work, or score output quality.

## Public CLI Surface

Top-level commands currently exposed by `agvv`:

- `agvv daemon`
- `agvv projects`
- `agvv tasks`
- `agvv feedback`

The codebase still contains `run/session/checkpoint` modules under `src/agvv/core` and `src/agvv/cli`, but these are not mounted in the current top-level CLI entrypoint.

## Core Principles

- Filesystem is source of truth. Persistent state is stored under each repository's `.agvv/`.
- Checkpoint equals Git commit. Successful runs must produce a new readable commit.
- Tool, not decider. agvv performs mechanical actions; orchestration policy stays outside agvv.
- Small model. Task, Run, and checkpoint metadata are the core state objects.

## Installation

```bash
pip install -e .
# or
uv pip install -e .
```

Requires Python `>=3.10`.

## Quick Start

1. Create a task markdown file (front matter `name` is required):

```markdown
---
name: fix-login-bug
---

## Goal
Fix login white-screen on Safari 17.

## Acceptance Criteria
- Login succeeds on Safari 17.
- Existing tests still pass.
```

2. Add task (project is auto-initialized and auto-registered when valid):

```bash
agvv tasks add --project ~/projects/my-app --file task.md --agent codex
```

3. Observe status:

```bash
agvv projects show ~/projects/my-app
agvv tasks show fix-login-bug --project ~/projects/my-app
```

4. Merge when ready:

```bash
agvv tasks merge fix-login-bug --project ~/projects/my-app
```

## Task and Run Lifecycle

### Task states

- `pending`
- `running`
- `failed`
- `blocked`
- `done`

### What `tasks add` does

- ensures Git repo + initial commit (if missing)
- ensures project layout under `.agvv/`
- creates `.agvv/tasks/<name>/task.md`
- persists `auto_manage: true`
- writes queued feedback fields (`feedback_status`, `feedback_message`, `feedback_at`)
- auto-starts daemon unless `AGVV_SKIP_DAEMON_AUTOSTART` is truthy

### Daemon auto-run behavior

Daemon picks tasks when:

- `status == pending`
- `auto_manage` is truthy
- task has no prior runs (`run_number == 0`)

The run purpose is `implement`. Agent resolution order:

1. task front matter `agent`
2. project config `.agvv/config.json` field `default_agent`
3. fallback `claude`

### Run completion rules

- Any purpose with exit code `0` but no new checkpoint vs `base_commit` is marked `failed` (`finish_reason=no_new_checkpoint`).
- `review` runs must also write a non-empty report file (`report_path`), otherwise `failed` (`finish_reason=missing_review_report`).
- `implement`/`repair` runs can auto-commit dirty worktree changes via `agent_runner` after successful process exit.
- If task is auto-managed and run completes, task becomes `done`; otherwise it returns to `pending`.

### Merge behavior

`agvv tasks merge` requires:

- project primary worktree is on main branch (`main` or `master`, resolved by Git checks)
- project worktree is clean (ignoring `.agvv/` and `worktrees/`)

On success:

- merges `agvv/<task>` into main
- closes last session (best effort)
- removes task worktree/branch (best effort)
- archives task under `.agvv/tasks/archive/<date>-<task>`
- sets task status to `done`

On conflict:

- aborts merge
- marks task `blocked`
- returns conflicting file list

## CLI Reference

### `daemon`

```bash
agvv daemon start
agvv daemon stop
agvv daemon status
```

### `projects`

```bash
agvv projects
agvv projects list
agvv projects show <path>
agvv projects remove <path>
```

### `tasks`

```bash
agvv tasks [--project <path>]
agvv tasks list [--project <path>]
agvv tasks add --project <path> --file <task.md> [--create-project] [--agent <name>]
agvv tasks show <task-name> [--project <path>]
agvv tasks merge <task-name> [--project <path>]
```

### `feedback`

```bash
agvv feedback --title <text> [--body <text>] [--type bug|feature|refactor] [--issue]
```

Without `--issue`, feedback is only saved locally at `~/.agvv/feedback.json`.

## Configuration and Environment

### Project config (`.agvv/config.json`)

By default agvv writes:

- `agvv_repo`
- `hooks.after_create`
- `hooks.before_run`
- `hooks.after_run`

Optional fields used by runtime logic:

- `default_agent`

### Environment variables

- `AGVV_ACPX_BIN`: override acpx launcher (default: local `acpx`, else `npx acpx@latest`)
- `AGVV_ACPX_ARGS`: extra args before agent token
- `AGVV_ACPX_OPTS`: options inserted before agent token (for example `--approve-all --model gpt-5.4`)
- `AGVV_SKIP_DAEMON_AUTOSTART`: disable daemon autostart in `tasks add`
- `AGVV_REPO`: target repo for `agvv feedback --issue`

## Storage Layout

```text
<project>/
├── worktrees/
│   └── <task>/
└── .agvv/
    ├── config.json
    ├── hooks/
    │   ├── after_create.sh
    │   ├── before_run.sh
    │   └── after_run.sh
    └── tasks/
        ├── <task>/
        │   ├── task.md
        │   └── runs/
        │       ├── 001-implement.md
        │       ├── 001-implement.runtime.json
        │       └── 001-implement.log
        └── archive/
            └── 2026-04-02-<task>/

~/.agvv/
├── projects.json
├── daemon.pid
├── daemon.log
└── feedback.json
```

## Development and Testing

```bash
agvv --help
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_cli_output
PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_robustness
AGVV_RUN_REAL_AGENT_E2E=1 PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_real_agent_e2e
```

## License

MIT
