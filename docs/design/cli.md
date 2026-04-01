# agvv CLI Reference

This guide is optimized for agents: each command tells you when to use it, which parameters matter, and what result to expect.

## Global patterns

- `--project <path>`: force target repository; use this to avoid ambiguous task lookup.
- Default output is JSON for agent-friendly parsing.
- Task names come from task front matter `name:`.

## daemons

When to use: monitor active runs and reconcile stale state.

Commands:

```bash
agvv daemons start
agvv daemons status
agvv daemons stop
```

## projects

When to use: inspect or clean up repositories managed by agvv.

Commands:

```bash
agvv projects
agvv projects remove <repo_path>
```

Parameters:

- `<repo_path>`: repository directory.

## tasks

When to use: create work items, inspect task state, or merge completed work.

Commands:

```bash
agvv tasks add --project <repo_path> --file <task_md>
agvv tasks [--project <repo_path>]
agvv tasks show <task_name> [--project <repo_path>]
agvv tasks merge <task_name> [--project <repo_path>]
```

Parameters:

- `--project`: repository directory (auto-registered and initialized if needed).
- `--file`: markdown file with front matter `name`.
- `<task_name>`: unique task id in project.

## runs

When to use: execute task work with an agent.

Commands:

```bash
agvv runs start <task_name> --purpose <implement|review|test|repair> --agent <agent> [--base-branch <ref>] [--project <repo_path>]
agvv runs status [--project <repo_path>]
agvv runs stop <task_name> [--project <repo_path>]
```

Parameters:

- `--purpose`: execution intent and completion gate.
- `--agent`: acpx agent type (for example `codex`).
- `--base-branch`: baseline ref for `review` and `test` (recommended).

Completion behavior:

- `implement/repair`: must create a new commit.
- `review`: must write a non-empty review report file.
- `test`: exit code determines pass/fail.

## sessions

When to use: manage persistent acpx context per task.

Commands:

```bash
agvv sessions ensure <task_name> --agent <agent> [--project <repo_path>]
agvv sessions status <task_name> --agent <agent> [--project <repo_path>]
agvv sessions close <task_name> --agent <agent> [--project <repo_path>]
agvv sessions list --agent <agent>
```

## checkpoints

When to use: read the latest durable output for a task.

Command:

```bash
agvv checkpoints show <task_name> [--project <repo_path>]
```

If latest run has no checkpoint, output includes latest-failure context and may include previous checkpoint.

## Agent friendly example flow

```bash
agvv tasks add --project /repo/app --file /tmp/fix-login.md
agvv runs start fix-login --purpose implement --agent codex --project /repo/app
agvv checkpoints show fix-login --project /repo/app
agvv runs start review-login --purpose review --agent codex --base-branch agvv/fix-login --project /repo/app
agvv tasks merge fix-login --project /repo/app
```
