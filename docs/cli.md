# agvv CLI Reference

This guide is optimized for agents: each command tells you when to use it, which parameters matter, and what result to expect.

## Global patterns

- `--project <path>`: force target repository; use this to avoid ambiguous task lookup.
- Default output is JSON for agent-friendly parsing.
- Task names come from task front matter `name:`.

## daemon

When to use: monitor active runs and reconcile stale state.

Commands:

```bash
agvv daemon start
agvv daemon status
agvv daemon stop
```

## project

When to use: register or inspect repositories managed by agvv.

Commands:

```bash
agvv project add <repo_path>
agvv project list
agvv project remove <repo_path>
```

Parameters:

- `<repo_path>`: repository directory.

## task

When to use: create work items, inspect task state, or merge completed work.

Commands:

```bash
agvv task add --project <repo_path> --file <task_md>
agvv task list [--project <repo_path>]
agvv task show <task_name> [--project <repo_path>]
agvv task merge <task_name> [--project <repo_path>]
```

Parameters:

- `--file`: markdown file with front matter `name`.
- `<task_name>`: unique task id in project.

## run

When to use: execute task work with an agent.

Commands:

```bash
agvv run start <task_name> --purpose <implement|review|test|repair> --agent <agent> [--base-branch <ref>] [--project <repo_path>]
agvv run status [--project <repo_path>]
agvv run stop <task_name> [--project <repo_path>]
```

Parameters:

- `--purpose`: execution intent and completion gate.
- `--agent`: acpx agent type (for example `codex`).
- `--base-branch`: baseline ref for `review` and `test` (recommended).

Completion behavior:

- `implement/repair`: must create a new commit.
- `review`: must write a non-empty review report file.
- `test`: exit code determines pass/fail.

## session

When to use: manage persistent acpx context per task.

Commands:

```bash
agvv session ensure <task_name> --agent <agent> [--project <repo_path>]
agvv session status <task_name> --agent <agent> [--project <repo_path>]
agvv session close <task_name> --agent <agent> [--project <repo_path>]
agvv session list --agent <agent>
```

## checkpoint

When to use: read the latest durable output for a task.

Command:

```bash
agvv checkpoint show <task_name> [--project <repo_path>]
```

If latest run has no checkpoint, output includes latest-failure context and may include previous checkpoint.

## Agent friendly example flow

```bash
agvv project add /repo/app
agvv task add --project /repo/app --file /tmp/fix-login.md
agvv run start fix-login --purpose implement --agent codex --project /repo/app
agvv checkpoint show fix-login --project /repo/app
agvv run start review-login --purpose review --agent codex --base-branch agvv/fix-login --project /repo/app
agvv task merge fix-login --project /repo/app
```
