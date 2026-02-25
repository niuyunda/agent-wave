---
name: agent-wave
description: Agent Wave workflow for AI Agent orchestration. Use the `agvv` CLI to enforce parallel Git worktree development, reduce failures, and save token usage.
---

# Agent Wave Skill

Project name: `Agent Wave`  
CLI command: `agvv`

This skill standardizes project setup, branch/worktree isolation, and task context capture so multiple agents can work safely in parallel with consistent guardrails.

## Scope

Use this skill for all code tasks:

- New project initialization
- Existing project adoption and refactor
- Feature development
- Bug fixing
- Ongoing maintenance changes

## Core Model

Every project follows this layout:

- `<base>/<project>/repo.git` - bare repository
- `<base>/<project>/main` - protected integration worktree
- `<base>/<project>/<feature>` - task-specific implementation worktree

Agent context is stored per feature:

- `<base>/<project>/<feature>/.agvv/context.json`

## Non-Negotiable Rules

1. Never implement directly in `<project>/main`.
2. Every task uses `agvv feature start` to create/reuse an isolated feature worktree.
3. Build, test, and commit only inside that feature worktree.
4. Merge through PR workflow.
5. After merge, run cleanup (`agvv feature cleanup`).
6. Always pass explicit `--base-dir` in automation contexts.

## Canonical Workflow

### 1) Project Bootstrapping

For a new project:

```bash
agvv project init <project> --base-dir <base_dir>
```

For an existing repository:

```bash
agvv project adopt <existing_repo_path> <project> --base-dir <base_dir>
```

### 2) Start Feature Work

```bash
agvv feature start <project> <feature> --base-dir <base_dir>
```

### 3) Implement and Validate

- `cd` into `<base>/<project>/<feature>`
- Run coding, formatting, tests, and checks
- Commit on the feature branch only

### 4) Merge and Cleanup

After PR merge:

```bash
agvv feature cleanup <project> <feature> --base-dir <base_dir>
```

Keep branch temporarily if needed:

```bash
agvv feature cleanup <project> <feature> --base-dir <base_dir> --keep-branch
```

## Agent Parameter Contract

Use these options with `agvv feature start` to capture execution context:

- `--agent <agent_name_or_id>`: source agent identity
- `--task-id <task_execution_id>`: task/run identifier
- `--ticket <issue_id>`: external tracker ID
- `--param KEY=VALUE` (repeatable): arbitrary structured context
- `--mkdir <path>` (repeatable): precreate task directories
- `--from-branch <branch>`: base branch for new feature branch (default: `main`)

Example:

```bash
agvv feature start <project> <feature> \
  --base-dir <base_dir> \
  --from-branch main \
  --agent codex \
  --task-id run-20260225-001 \
  --ticket PROJ-123 \
  --param language=python \
  --param change_type=feature \
  --mkdir src \
  --mkdir tests
```

## Operational Guidance for Agents

- Resolve all paths before execution.
- Treat `main` as read-only integration surface.
- Keep feature naming deterministic (`feat-*`, `fix-*`, `refactor-*`).
- Write meaningful `--param` metadata for traceability.
- Prefer short-lived feature worktrees and fast cleanup.

## Anti-Patterns

Do not:

- Edit directly in `<project>/main`
- Reuse one feature worktree for unrelated tasks
- Skip context metadata for automated agent tasks
- Keep stale merged worktrees/branches indefinitely

## Minimal Command Reference

```bash
agvv project init <project> --base-dir <base_dir>
agvv project adopt <existing_repo_path> <project> --base-dir <base_dir>
agvv feature start <project> <feature> --base-dir <base_dir> [options...]
agvv feature cleanup <project> <feature> --base-dir <base_dir> [--keep-branch]
```
