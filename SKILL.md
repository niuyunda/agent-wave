---
name: agent-wave
description: Strict instructions for an Agent to execute coding tasks using the `agvv` CLI.
---

# Agent Wave (`agvv`) Skill Instructions

You are an AI Agent. When asked to use `agvv` to run a coding task, you MUST strictly follow this standard operating procedure. DO NOT deviate from these rules.

## Allowed Commands

You are ONLY permitted to use the following `agvv` commands:
- `agvv task run --spec <path> [--project-dir <path>]`
- `agvv task status`
- `agvv task retry --task-id <id>`
- `agvv task cleanup --task-id <id>`
- `agvv daemon run --once`

*(If running from source tree, prefix with `uv run`, eg: `uv run agvv task status`)*

## `task.json` Creation Rules

When generating the `task.json` file for the user, you MUST adhere to the following schema:

**REQUIRED Fields:**
1. `project_name` (string): The slugified name of the project.
2. `feature` (string): The branch name. **CRITICAL: MUST perfectly match regex `^[A-Za-z0-9_-]+$`.** Absolutely no spaces or punctuations. Example: `feat-login-api`.
3. `repo` (string): The repository URL or owner/repo format.
4. `task_doc` (string): Path to the Markdown file containing detailed instructions. **CRITICAL: MUST end with `.md`.**

**Prohibited Fields in `task.json`:**
DO NOT put detailed instructions, `requirements`, or `constraints` inside `task.json`. ALL complex text MUST go into the Markdown file referenced by `task_doc`.

## Execution Protocol

Execute these steps IN EXACT ORDER:

### Step 1: Validate Setup
Ensure the `task.json` and `<task_doc>.md` files exist on disk and meet all rules above. If `feature` contains spaces, you MUST fix it to be a slug before proceeding.

### Step 2: Run Task
Execute the task generation.
- **If operating on an existing repository:** `agvv task run --spec ./task.json --project-dir <path_to_existing_repo>`
- **If creating a new project from scratch:** `agvv task run --spec ./task.json`

### Step 3: Monitor State
Run `agvv task status` to note the `task-id`.
Because the task runs in a background tmux session, you MUST use the daemon to sync the state:
- Execute `agvv daemon run --once` to poll the status.
- Repeat `agvv task status` + `agvv daemon run --once` until the task state transitions from `RUNNING` to a terminal state (such as `DONE` or `TIMED_OUT`).

### Step 4: Handle Failure (If Applicable)
If the task fails or times out:
- Read the error from `agvv task status`.
- Resolve the underlying issue (e.g. fix `task.json`).
- Run `agvv task retry --task-id <task_id>`.

### Step 5: Cleanup
Once the user confirms the task is completed and successful, you MUST clean up the worktree to free system resources:
- Run `agvv task cleanup --task-id <task_id>`
