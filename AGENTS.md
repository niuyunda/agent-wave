# AGENTS.md for Agent Wave (`agvv`)

This document defines high-level engineering principles for agents working on the `agvv` project.

## 1) First-Principles Goals

Every change should improve at least one of these fundamentals:

- Isolation: task development must not pollute the main workspace.
- Reliability: task state and lifecycle must be durable and recoverable.
- Clarity: behavior and code intent should be easy to understand.
- Iteration speed: changes should be testable quickly and repeatedly.

If a change does not improve these fundamentals, simplify or remove it.

## 2) Core Principles

- Prefer essence over form: optimize for outcomes, not old structure.
- Keep the system small: do not add abstractions/dependencies without clear payoff.
- Make failures explicit: errors must be actionable and observable.
- Keep behavior auditable: state transitions and side effects should be traceable.
- Preserve user trust: avoid surprising behavior changes unless explicitly required.

## 3) Mandatory Development Workflow (Use `agvv` Every Time)

For every development task, agents must use `agvv` to create an isolated worktree before coding.
Do not develop directly in the main workspace.

Required loop:

1. Create task input (`task.md`).
2. Start task with `agvv task run` (use `--project-dir` for existing repo).
3. Develop inside the new feature worktree under `worktrees/<feat-slug>/`.
4. Run checks/tests continuously while developing.
5. If any issue appears while using `agvv`, record it immediately (see section 4).
6. Reconcile state with `agvv daemon run --once` and inspect `agvv task status`.
7. If blocked/failing, retry with `agvv task retry` after fixing root cause.
8. After completion, clean up with `agvv task cleanup`.

This is a strict operational rule: develop by using `agvv`, not beside `agvv`.

## Project Layout

```
<project>/
  .git/                  # git repository metadata
  worktrees/             # feature worktrees (excluded from git)
    feat-<slug>/        # one per task
  # project files live directly in <project>/
```

- The project directory itself is the main worktree (no `main/` subdirectory).
- Feature worktrees live under `worktrees/<feat-slug>/`.
- `worktrees/` is declared in `.git/info/exclude` so git ignores it.
- Feature names allow `/` for branch-style naming (`feat/demo`); directory name converts `/` to `-`.
- Reserved feature names: `main`, `worktrees`.

### Feature Branch Naming

- Branch names: `feat/<slug>`, `fix/<slug>`, `refactor/<slug>`, `chore/<slug>`
- Worktree directories: `feat-<slug>`, `fix-<slug>`, etc. (slash -> hyphen)

### Conflict & Recovery

If `git worktree add` fails or the target branch already exists, **do not attempt automatic recovery**. Stop and report to the orchestrator with the output of:

```bash
git worktree list
git branch -v
```

The orchestrator decides whether to force-remove a stale worktree, delete and restart the branch, or resume existing work. Subagents do not make structural decisions about the repo.

## 4) Problem Logging (Required)

During each task, record issues found while using `agvv` itself, including:

- command UX friction
- unclear errors/messages
- state-machine edge cases
- worktree/session lifecycle surprises
- doc/spec mismatches

At minimum, capture for each issue:

- trigger command/input
- observed behavior
- expected behavior
- temporary workaround (if any)

Store issue records using this fixed location and naming:

- directory: `docs/agvv-issues/<YYYY-MM-DD>/`
- filename: `<task_id>__<short-kebab-topic>.md`
  - example: `demo-feat_x-20260305101530__daemon-state-not-advancing.md`

Repository policy for issue records:

- default: commit and push issue records into this repository
- exceptions: if record contains secrets/private data, redact first, then commit
- if an issue is purely local and non-actionable for the project, do not commit it; mention it in task summary as local-only

These findings should feed the next iteration.

## 5) Fast Iteration Standard

Use a short loop: implement -> test -> observe -> adjust.

Minimum checks before finishing non-trivial code or test changes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run interrogate . --fail-under=80 --quiet \
  --exclude tests --exclude scripts --exclude dist --exclude tmp \
  --exclude agvv/__init__.py --exclude agvv/cli.py \
  --exclude agvv/orchestration/__init__.py --exclude agvv/runtime/__init__.py --exclude agvv/shared/__init__.py
uv run interrogate agvv/runtime agvv/orchestration agvv/shared --fail-under=100 --quiet \
  --exclude agvv/orchestration/__init__.py --exclude agvv/runtime/__init__.py --exclude agvv/shared/__init__.py
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing
```

For docs-only edits, running the full suite is optional.
In docs-only cases, at least verify the changed docs are internally consistent with current code behavior.

## 6) Refactoring Policy

Refactoring is encouraged when it reduces complexity or improves correctness.
You may reshape modules and boundaries if the result is simpler and better tested.

When behavior or contract changes, update in the same task:

- tests (`tests/cli`, `tests/runtime`, `tests/orchestration` as applicable)
- user docs (`README.md`, `README.zh-CN.md`)
- agent docs (`SKILL.md`, this file if principles change)

## 7) Final Rule

Choose the design that makes `agvv` easier to trust, easier to evolve, and easier to use in real agent workflows.
