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
agvv projects list
agvv projects show <repo_path>
agvv projects remove <repo_path>
```

Parameters:

- `<repo_path>`: repository directory.

## tasks

When to use: create work items, inspect task state, or merge completed work.

Commands:

```bash
agvv tasks add --project <repo_path> --file <task_md> [--create-project] [--agent <name>]
agvv tasks [--project <repo_path>]
agvv tasks list [--project <repo_path>]
agvv tasks show <task_name> [--project <repo_path>]
agvv tasks merge <task_name> [--project <repo_path>]
```

Parameters:

- `--project`: repository directory (auto-registered and initialized if needed).
- `--file`: markdown file with front matter `name`.
- `--create-project`: create `--project` directory when it does not exist.
- `--agent`: optional acpx agent name for daemon auto-run (for example `codex`, `claude`).
- `<task_name>`: unique task id in project.

`tasks add` always enables automatic orchestration and queues the task for daemon execution.

## Agent friendly example flow

```bash
agvv tasks add --project /repo/app --file /tmp/fix-login.md
agvv projects show /repo/app
agvv tasks show fix-login --project /repo/app
agvv tasks merge fix-login --project /repo/app
```
