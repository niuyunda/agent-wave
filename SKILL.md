# agvv

## 1) Role Boundary

`agvv` is deterministic orchestration infrastructure, not a coding-quality judge.

It is responsible for:

- task/run state files under `.agvv/`
- daemon-driven auto runs
- worktree/process lifecycle
- Git-backed completion checkpoints

The orchestrator agent is responsible for planning, retry policy, and merge decisions.

## 2) Authoritative CLI Surface

Top-level commands:

- `agvv daemon`
- `agvv projects`
- `agvv tasks`
- `agvv feedback`

Not available as top-level commands:

- `runs`
- `sessions`
- `checkpoints`
- `status`

Use `projects` and `tasks` for state inspection.

## 3) Operational Query Commands

Projects:

- `agvv projects`
- `agvv projects list`
- `agvv projects show <repo_path>`
- `agvv projects remove <repo_path>`

Tasks:

- `agvv tasks [--project <repo_path>]`
- `agvv tasks list [--project <repo_path>]`
- `agvv tasks show <task_name> [--project <repo_path>]`
- `agvv tasks add --project <repo_path> --file <task_md> [--create-project] [--agent <name>]`
- `agvv tasks merge <task_name> [--project <repo_path>]`

Daemon:

- `agvv daemon start`
- `agvv daemon status`
- `agvv daemon stop`

Feedback:

- `agvv feedback --title <text> [--body <text>] [--type bug|feature|refactor] [--issue]`

## 4) `tasks add` Side Effects

`tasks add` does all of the following:

- ensures project repo/layout (`.agvv/config.json`, hooks directory, task/archive folders)
- auto-registers project in `~/.agvv/projects.json`
- creates task and `runs/` directory
- forces `auto_manage: true`
- sets queued feedback fields in task front matter
- auto-starts daemon unless `AGVV_SKIP_DAEMON_AUTOSTART` is truthy

Agent selection for daemon auto-runs:

1. `task.md` field `agent` (or `--agent` override)
2. project config `default_agent`
3. fallback `claude`

## 5) Task Contract

Required `task.md` front matter:

- `name`

Validation rules:

- `name` must match `[A-Za-z0-9._-]+`
- duplicate names are rejected across active tasks and archive
- invalid incoming `status` is rejected

All extra front matter keys are preserved.

## 6) Runtime and Completion Semantics

- Every successful run must create a new checkpoint commit versus run `base_commit`.
- `review` runs must also write a non-empty report file at `report_path`.
- Implement/repair runs can auto-commit pending work via `agent_runner` after a zero exit code.
- Auto-managed task: completed run -> task `done`.
- Non-auto-managed task: completed run -> task `pending`.
- Merge conflict sets task `blocked`.

## 7) Minimal Orchestration Loop

```bash
agvv tasks add --project /repo/app --file /tmp/fix-login.md --agent codex
agvv projects show /repo/app
agvv tasks show fix-login --project /repo/app
agvv tasks merge fix-login --project /repo/app
```

Run discipline:

- inspect `tasks show` before merge
- avoid merge when task status is `failed` or `blocked`
- pass `--project` when task name might not be globally unique

## 8) Issue Capture

When behavior is incorrect, file reproducible evidence in:

- `docs/issues/`
- `docs/issues/ISSUE_TEMPLATE.md`
