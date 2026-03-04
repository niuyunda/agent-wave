# AGVV E2E Report (Calculator Project, Rerun)

## Scope

- Test directory: `/home/yunda/projects/agent-wave/main/e2e_test_project`
- DB log: `/home/yunda/projects/agent-wave/main/e2e_test_project/artifacts/tasks_rerun.db`
- Command log: `/home/yunda/projects/agent-wave/main/e2e_test_project/artifacts/e2e_rerun.log`
- Fake GitHub CLI used for deterministic local PR simulation: `/home/yunda/projects/agent-wave/main/e2e_test_project/bin/gh`

## Functional Coverage

- `project init`: pass
- `project adopt`: pass
- `task run`: pass (main/no-op/timeout specs)
- `task status`: pass
- `daemon run --once`: pass (`coding` / `pr_open` / `pr_merged` / `timed_out`)
- `daemon run` loop mode (`--max-loops 1`): pass
- `task retry`: pass (failed task recovered after remote config)
- `task cleanup`: pass (normal + `--force`)

## Calculator Project Result

- Created via AGVV workflow in branch `feat_calculator`.
- Result files:
  - `src/calculator.py`
  - `tests/test_calculator.py`
- Validation run in checkout directory: `2 passed`.

## Log-Based Findings

1. Missing remote is now surfaced clearly (improved behavior, still a UX gap).
   - Evidence: `calc_task_main` failed with:
     - `No git remote 'origin' configured ... Configure it with git remote add origin <url> or set branch_remote in task spec.`
   - Assessment:
     - This is no longer a hidden failure.
     - But first-time users still hit a hard-stop right after `project init` unless they know to add remote manually.

2. `.agvv` internal metadata is no longer treated as user code (fixed).
   - Evidence: `calc_task_no_commit` now fails with:
     - `Task produced no commits ahead of base branch 'main'.`
   - Additional evidence:
     - remote branch `feat_no_commit` was not created.
   - Assessment:
     - Previous false-positive PR progression issue is resolved.

3. Timeout path works as expected.
   - Evidence: `calc_task_timeout` moved from `pr_open` to `timed_out`, then cleanup succeeded.

## Suggested Follow-Ups

1. Add a user-facing remote setup command.
   - Example: `agvv project set-remote --project-name <name> --remote origin --url <repo-url>`.
   - This would convert current manual git step into first-class AGVV workflow.

2. Improve `project init` guidance output.
   - After init, print a next-step hint when no remote exists:
     - "Run `git -C <repo.git> remote add origin <url>` before task finalize."

3. Add an integration test for init-to-finalize UX.
   - Verify that a fresh `project init` repo with no remote produces the actionable error message (current behavior), and optionally provide CLI hint text.

