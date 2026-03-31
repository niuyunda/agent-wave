# agvv Agent Skill (First Principles)

## 1) What agvv is

`agvv` is a **deterministic orchestration layer**, not an autonomous coding agent.  
It does three things: manage state, manage Git worktrees/branches, and record run outcomes.

First-principles constraints:

- Truth lives in files and Git (`.agvv/` + commits), not in memory.
- Durable outputs must be replayable (checkpoint commit or review report file).
- Quality judgment and prioritization belong to the agent, not to agvv.

## 2) What agvv can and cannot do

Can do:

- project/task registration
- run start/stop
- state and checkpoint inspection
- merge and archive task branches

Cannot do:

- decide whether code quality is acceptable
- choose retry strategy
- resolve business conflicts automatically

## 3) Task markdown (`task.md`)

When authoring or editing the markdown file you pass to `agvv task add --file`:

- **Reference only:** open `docs/task-template.md` in this repository as an **example shape**, not a mandatory schema. Tasks may be shorter, reorder sections, or skip prose—the goal is useful signal, not bureaucracy.
- **Worth keeping tight:** **acceptance criteria** (checkable outcomes), **how to test / verify** (commands or explicit manual steps), and **definition of done** (what “finished” means, including no scope creep). Those reduce low-quality or untested handoffs; everything else can stay loose so the agent is not over-constrained.

## 4) Run model (hard requirements)

- Task: one unit of work (`name` must be unique in a project).
- Run: one execution (`implement | review | test | repair`).
- Completion gates:
  - All purposes: MUST create a **new commit** vs. the run’s recorded baseline (`no_new_checkpoint` on failure).
  - `review`: MUST also write a non-empty report file (default `reports/agvv/<task>/<run>-review.md`; otherwise `missing_review_report`).

## 5) Branch and baseline policy

- `implement/repair`: run on `agvv/<task>`.
- `review/test`: by default, explicitly pass `--base-branch=<ref>` to avoid wrong baselines.
- With `--base-branch`, execution is detached; do not expect a new task branch.

## 6) Agent execution protocol (minimal loop)

```bash
agvv task list --project <repo>
agvv run start <task> --purpose=implement --agent=codex
agvv run start <task> --purpose=review --agent=codex --base-branch=<ref>
agvv run start <task> --purpose=test --agent=codex --base-branch=<ref>
agvv task show <task>
agvv checkpoint show <task>
agvv task merge <task>
```

Execution rules:

- Never treat `exit_code=0` as sufficient success evidence.
- Never merge when task status is `failed` or `blocked`.
- `task=pending` with latest run `completed` is normal (waiting for next action).
- For shell checks, use `python`; fallback to `python3` when unavailable.

## 7) Main commands and common parameters

### Project

- `agvv project add <repo_path>`
- `agvv project list`
- `agvv project remove <repo_path>`

### Task

- `agvv task add --project <repo_path> --file <task_md>`
- `agvv task list [--project <repo_path>] [--json]`
- `agvv task show <task_name> [--project <repo_path>]`
- `agvv task merge <task_name> [--project <repo_path>]`

### Run

- `agvv run start <task_name> --purpose <implement|review|test|repair> --agent <agent> [--base-branch <ref>] [--project <repo_path>]`
- `agvv run stop <task_name> [--project <repo_path>]`
- `agvv run status [--project <repo_path>] [--json]`

### Session

- `agvv session ensure <task_name> --agent <agent> [--project <repo_path>]`
- `agvv session status <task_name> --agent <agent> [--project <repo_path>]`
- `agvv session close <task_name> --agent <agent> [--project <repo_path>]`
- `agvv session list --agent <agent> [--project <repo_path>]`

### Checkpoint and daemon

- `agvv checkpoint show <task_name> [--project <repo_path>] [--json]`
- `agvv daemon start | status | stop`

Common high-frequency parameters:

- `--project`: avoid ambiguous project resolution.
- `--json`: machine-readable output for agent parsing.
- `--purpose`: required on `run start`; drives completion gate.
- `--agent`: required on `run start/session`.
- `--base-branch`: strongly recommended for `review/test`.

## 8) Example usage

```bash
# 1) Register project and add task
agvv project add /repo/app
agvv task add --project /repo/app --file /tmp/fix-login.md

# 2) Implement
agvv run start fix-login --purpose implement --agent codex --project /repo/app
agvv run status --project /repo/app --json
agvv checkpoint show fix-login --project /repo/app

# 3) Review and test against implementation branch
agvv run start review-login --purpose review --agent codex --base-branch agvv/fix-login --project /repo/app
agvv run start test-login --purpose test --agent codex --base-branch agvv/fix-login --project /repo/app

# 4) Merge when ready
agvv task show fix-login --project /repo/app
agvv task merge fix-login --project /repo/app
```

## 9) Failure handling

- If any hard gate is not met, treat the run as invalid and re-run with corrected inputs.
- When ambiguous, inspect `task show` and `checkpoint show` before deciding next action.

## 10) Issue tracking

When something goes wrong with agvv, document it in the codebase:

**Location:** `/home/yunda/projects/agent-wave/docs/issues/`

**Template:** `docs/issues/ISSUE_TEMPLATE.md` — copy it, rename with date and descriptive name (e.g. `2026-03-31-base-branch-wrong-commit.md`).

**Required frontmatter fields:**

- `name` — short slug
- `date` — YYYY-MM-DD
- `type` — bug | enhancement | question | investigation
- `severity` — critical | high | medium | low | none
- `status` — open | in-progress | resolved | wonotfix
- `reproduced` — true | false
- `affects` — implement | review | test | repair | merge | daemon | cli | unknown

**Write the issue before fixing** — document what happened, steps to reproduce, and evidence. Fix the issue after.

**Default agent:** `claude` (changed from `codex` as of 2026-03-31).