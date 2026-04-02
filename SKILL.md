# agvv Agent Skill (Current CLI)

## 1) What agvv is

`agvv` is a deterministic orchestration layer, not an autonomous coding agent.

It focuses on:
- file-backed task state (`.agvv/`)
- daemon-driven automatic execution
- durable run outcomes in Git/history

Quality judgment and prioritization still belong to the orchestrator agent.

## 2) Command surface (authoritative)

Current top-level commands:
- `agvv daemon`
- `agvv projects`
- `agvv tasks`
- `agvv feedback`

Removed from CLI surface:
- `runs`
- `sessions`
- `checkpoints`
- `status`

Use `projects/tasks` to inspect state.

Daemon control:
- `agvv daemon start`
- `agvv daemon status`
- `agvv daemon stop`

## 3) Projects and tasks query model

### Projects

- `agvv projects` (list all)
- `agvv projects list` (alias of `agvv projects`)
- `agvv projects show <repo_path>` (single project + task statuses)
- `agvv projects remove <repo_path>`

### Tasks

- `agvv tasks [--project <repo_path>]` (list tasks)
- `agvv tasks list [--project <repo_path>]` (alias of `agvv tasks`)
- `agvv tasks show <task_name> [--project <repo_path>]` (single task detail)
- `agvv tasks add --project <repo_path> --file <task_md>`
- `agvv tasks merge <task_name> [--project <repo_path>]`

## 4) Automatic orchestration behavior

- `tasks add` auto-registers/initializes project metadata when needed.
- `tasks add` marks task `auto_manage=true` and queues feedback for daemon pickup.
- daemon picks pending auto-managed tasks and starts implement runs automatically.
- orchestrator observes progress via `projects`, `projects show`, and `tasks show`.

## 5) Task name constraints and uniqueness

Hard requirements on `task.md` frontmatter:
- must include `name`
- `name` pattern: `[A-Za-z0-9._-]+`
- name must be unique in current tasks and in archive

Duplicate names are rejected with a clear error.

## 6) Task markdown guidance

When authoring the markdown passed to `tasks add --file`:
- use `docs/task-template.md` as shape reference only
- keep acceptance criteria and verification steps explicit
- keep content concise and executable

## 7) Minimal execution loop

```bash
# 1) add task (daemon will orchestrate)
agvv tasks add --project /repo/app --file /tmp/fix-login.md

# 2) observe project/task state
agvv projects
agvv projects show /repo/app
agvv tasks show fix-login --project /repo/app

# 3) merge when task is ready
agvv tasks merge fix-login --project /repo/app
```

Execution rules:
- never merge when task status is `failed` or `blocked`
- inspect `tasks show` before merge
- use `python`; fallback to `python3` when unavailable

## 8) Issue tracking

When agvv behaves incorrectly, document in:
- `docs/issues/`
- using `docs/issues/ISSUE_TEMPLATE.md`

Write the issue before fixing: include reproduction and evidence.
