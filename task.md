---
project_name: agent-wave
feature: chore/multi-agent-schema-phase1
repo: yunda/agent-wave
from_branch: main
---

Implement the first phase of the multi-agent orchestration refactor.

- Add additive SQLite schema primitives for workflows, task_attempts, worktree_leases, and task_dependencies.
- Add compatibility task columns and safe migration behavior for existing databases.
- Persist attempt records for launch/retry/reconcile on the current single-task flow without breaking existing CLI behavior.
- Add tests for migration compatibility and attempt persistence.
