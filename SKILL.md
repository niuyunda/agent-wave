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

## 3) Run model (hard requirements)

- Task: one unit of work (`name` must be unique in a project).
- Run: one execution (`implement | review | test | repair`).
- Completion gates:
  - `implement/repair`: MUST create a **new commit** (`no_new_checkpoint` on failure).
  - `review`: MUST write a non-empty report file (default `reports/agvv/<task>/<run>-review.md`; otherwise `missing_review_report`).
  - `test`: exit code determines pass/fail; new commit is optional.

## 4) Branch and baseline policy

- `implement/repair`: run on `agvv/<task>`.
- `review/test`: by default, explicitly pass `--base-branch=<ref>` to avoid wrong baselines.
- With `--base-branch`, execution is detached; do not expect a new task branch.

## 5) Agent execution protocol (minimal loop)

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

## 6) Failure handling

- If any hard gate is not met, treat the run as invalid and re-run with corrected inputs.
- When ambiguous, inspect `task show` and `checkpoint show` before deciding next action.
