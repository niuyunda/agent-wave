# Checkpoint-First Multi-Agent Orchestration Spec

## Document Purpose

This document is the implementation specification for coding agents modifying `agent-wave` (`agvv`).

It replaces the earlier session-centric multi-agent proposal with a more durable design:

- `agvv` must orchestrate multiple tasks in parallel
- each task may go through multiple coding and verification cycles
- any runtime session may crash or become unavailable
- work must continue from durable checkpoints rather than depending on chat history
- the first implementation remains local-first and ACP-backed
- the architecture must still leave a clean extension point for future cloud runtimes

This document is intentionally operational. A coding agent should be able to implement the design from this file alone, without prior chat context.

## First-Principles Problem Statement

`agvv` is currently effective as a single-task runner:

- one task creates or reuses one worktree
- one task launches one coding session
- one task stores one current runtime identity
- one daemon loop reconciles `pending` and `running`

That model fails once real orchestration begins. In a real multi-agent workflow:

- one project may have multiple tasks in flight at once
- coding and testing are different agents and therefore different sessions
- a completed coding step must be verified before the task is considered done
- failed verification must route back to the original coding line of work
- any session may hang, die, or become unrecoverable
- the orchestrator still needs enough history to continue the job safely

From first principles, the system must always answer four questions:

1. What work exists?
2. What has been tried for each unit of work?
3. What code workspace is currently authoritative for that work?
4. If the current runtime disappears, what durable state is sufficient to continue?

If `agvv` cannot answer those four questions from durable state plus the repository contents, it is not yet a reliable orchestrator.

## Core Design Thesis

The system must be **checkpoint-first**, not **session-first**.

That means:

- correctness must not depend on resuming the same runtime session
- any phase boundary that matters for future decisions must create a durable checkpoint
- work continuity must come from repository state, checkpoint artifacts, and durable metadata
- resuming the same session is only a speed optimization when it is safe and useful

The controlling idea is:

**A session may disappear at any time. A task must still be able to continue and close the loop.**

## What Must Be Preserved

The design should preserve only the structures required for reliable orchestration:

1. `Workflow`
   A top-level container for a coordinated run across one repository.

2. `Task`
   A business unit of work such as a feature, bugfix, or refactor.

3. `Attempt`
   One execution attempt by one role against one task.

4. `Session`
   The runtime session actually used by an attempt.

5. `Worktree`
   The code workspace allocated to the task in the first implementation.

6. `Checkpoint`
   A durable stage artifact that allows a later attempt to continue the task without previous chat history.

Everything else is secondary and must serve these primitives.

## Terminology

### Workflow

A workflow is a project-level orchestration run. It groups related tasks and gives the orchestrator a durable top-level object.

Examples:

- implement feature A, feature B, refactor C, and bugfix D in one repository
- run a batch of coding tasks and close each one through verification

The workflow abstraction is useful and should exist, but the first implementation should keep it simple. The essential behavior lives in task, attempt, worktree, and checkpoint handling.

### Task

A task is the durable definition of what needs to be accomplished.

Examples:

- add feature A
- add feature B
- refactor subsystem C
- fix bug D

A task is **not** a session and **not** a single execution. A task is complete only after its required verification loop succeeds.

### Attempt

An attempt is one role-specific execution attempt for one task.

Examples:

- coding attempt #1 for feature A
- testing attempt #1 for feature A
- coding fix attempt #2 for feature A after failed testing

`Attempt` exists because the orchestrator must reason about execution history independently from runtime session identity.

### Session

A session is the runtime identity used by an attempt.

For ACP-backed local runtimes this may include:

- provider
- model
- normalized command
- session name
- session id
- heartbeat metadata
- last observed runtime status

`Session` is not equivalent to `Attempt`.

An attempt answers:

- what role was being executed
- which task lifecycle step this execution belonged to
- whether this execution succeeded, failed, or timed out
- whether it was a retry or a fix continuation

A session answers:

- where the execution was running
- which runtime/provider was used
- whether the underlying session is alive
- whether resume is possible

In practice, one attempt often uses one session, but they are not the same abstraction. A later attempt may continue the same task from the latest checkpoint while using a completely new session.

### Worktree

For the first implementation, a worktree is the authoritative local code workspace for a task.

Its duties are:

- provide isolation between coding tasks
- preserve the exact filesystem view that verification must inspect
- remain available across multiple attempts of the same task
- be cleaned only when no active work still depends on it

The first implementation should remain local-first and use git worktrees. The design should still preserve a future upgrade path to more generic workspaces.

### Checkpoint

A checkpoint is the durable handoff point that allows work to continue after a session ends or crashes.

Primary rule:

**Every completed session produces a checkpoint.**

Examples:

- a coding session finishes and declares the implementation complete
- a testing session finishes and writes a test report
- a bugfix coding session finishes and writes the repair summary
- a final verification session passes
- a merge step completes

The checkpoint is not only a database row. It must create a durable artifact in the repository.

## Non-Goals

The first implementation must not try to solve everything:

- general arbitrary DAG scheduling across external systems
- autonomous merge conflict resolution
- forcing branch or worktree recovery after ambiguous git failures
- perfect provider-specific prompt optimization
- a full cloud runtime implementation in phase 1
- replacing ACP before the local checkpoint-first model is proven

## Design Requirements

The implementation must satisfy all of the following:

1. Multiple tasks can run in parallel.
2. Each task can go through multiple coding and verification cycles.
3. Coding and testing are different agents and therefore different sessions.
4. A completed coding session does not mean the task is complete.
5. Every completed session creates a checkpoint artifact.
6. If a session dies, a new session can continue from the latest checkpoint.
7. Verification runs against the same authoritative code worktree that coding produced.
8. The orchestrator can inspect the complete work record needed to decide the next action.
9. The first implementation works locally with ACP.
10. The runtime layer is modular enough that future providers can plug in cleanly.

## The Real Unit of Orchestration

The orchestrator is not merely managing a list of tasks. It is managing multiple independent **closed work loops**:

`task definition -> coding attempt -> verification attempt -> fix attempt -> verification attempt -> completion`

For example, for four project tasks:

- feature A
- feature B
- refactor C
- bugfix D

the orchestrator may initially start three or four coding attempts in parallel. Each task then evolves independently. One task may be waiting for verification while another is in fix mode and another is still in its first coding run.

This is why task, attempt, session, and worktree must be separated.

## Closed-Loop Execution Model

The standard lifecycle for a task is:

1. create task
2. allocate or attach worktree
3. start coding attempt
4. coding session completes
5. create coding checkpoint
6. start verification attempt in a new session
7. verification session completes
8. create verification checkpoint
9. if verification failed, request a fix and start a new coding attempt
10. if verification passed, mark task completed
11. optionally merge and clean up

The crucial rule is:

**Verification is always a new session.**

Reasons:

- the coding agent and the testing/review agent are not the same agent
- verification should not inherit implementation bias
- verification must inspect the resulting code state, not continue the coding conversation

Therefore:

- a coding session may optionally be resumed while it is still the active coding attempt
- a testing session always starts as a new session
- a review session also starts as a new session
- every cross-role handoff is checkpoint-based

## Checkpoint-First Continuity Model

### Why Checkpoints, Not Chat History

Chat history is not a reliable continuity layer:

- context windows are limited
- providers differ in retention and resume behavior
- long conversations accumulate noise
- old reasoning may become stale
- a runtime crash may make the entire session unavailable

By contrast, a checkpoint can be designed to be:

- durable
- explicit
- role-neutral
- easy to inspect
- safe to hand off to a brand new session

This is why the system's correctness must depend on checkpoints, not on session survival.

### What a Checkpoint Must Preserve

Each checkpoint must preserve the minimum durable facts required for a fresh session to continue:

- task identity
- workflow identity
- role that produced the checkpoint
- attempt identity
- current worktree
- current branch or ref
- stage reached
- summary of completed work
- summary of current verification result if one exists
- unresolved issues
- recommended next action
- timestamp

### Checkpoint Types

Suggested checkpoint types:

- `coding_complete`
- `verification_report`
- `fix_complete`
- `verification_passed`
- `merge_complete`
- `attempt_interrupted` (optional best-effort artifact; not required for correctness)

### Where Checkpoints Live

Each checkpoint must have:

- a durable metadata record in SQLite
- a repository artifact written to a stable path

Suggested repository path:

- `docs/agvv-checkpoints/<task-id>/<ordinal>-<checkpoint-type>.md`

The exact directory can change, but it must be stable, predictable, and committed with the task work.

### Checkpoint Content Template

Each checkpoint artifact should contain:

- task id
- workflow id
- attempt id
- role
- session id or session name when available
- worktree path
- branch name
- status summary
- completed work summary
- verification summary
- open issues
- recommended next action

If the checkpoint was produced after a failure or interruption, also include:

- failure summary
- whether the current code state is believed to be usable
- whether to retry on the same worktree
- whether a fresh worktree may be needed

## Code Persistence Policy

Three concepts must be kept separate:

1. `checkpoint`
   A stage boundary has been reached.

2. `code snapshot`
   The current code state has been durably saved.

3. `promotion`
   The current code state has been accepted as the version eligible for merge.

The correct policy is:

- every completed coding session creates a checkpoint
- if that session modified code, it must also create a commit on the task branch
- verification sessions usually create reports rather than code commits
- only code that has passed required verification is promoted to an accepted candidate
- only an accepted candidate may be merged

In other words:

**Every coding checkpoint should be committed. Not every coding checkpoint should be merged.**

This policy is required so that:

- crash recovery does not depend on dirty worktree state
- later sessions can continue from a known commit plus checkpoint artifact
- unverified code remains isolated on the task branch

## Attempt, Session, and Resume Semantics

### Why Attempt and Session Are Separate

An attempt is part of the task lifecycle.

A session is a runtime carrier.

That separation is necessary because:

- a failed attempt may end with a dead session
- a new attempt may continue the same task from the latest checkpoint
- a resumed session may still belong to the same attempt

The orchestrator should always reason in terms of attempts first and sessions second.

### Resume Is an Optimization, Not a Dependency

`resume_same_session` still has value:

- it may preserve useful short-term working memory
- it may reduce restart cost inside an ongoing coding phase
- it may be faster than creating a new session

But it must never be the primary correctness path.

The orchestrator must assume:

- a session can disappear at any time
- a fresh session can always continue from the latest checkpoint

Therefore the rule is:

**`restart_from_checkpoint` is the default continuity path. `resume_same_session` is an optional optimization when safe and useful.**

### When Resume Is Valid

Resume may be used only when all of the following hold:

- the session still exists
- the runtime reports it as resumable
- the task is still in the same role and same lifecycle phase
- there is reason to believe the remaining short-term context is valuable
- the session history has not become so large that it is now mostly noise

Resume is most appropriate for an interrupted coding phase that has not yet reached its next checkpoint.

### When a New Session Is Required

A new session is required when:

- the role changes from coding to verification
- the role changes from verification back to coding fix work
- the previous session is missing or unrecoverable
- the orchestrator intentionally restarts from the latest checkpoint
- the runtime provider changes
- the execution location changes

Testing always uses a new session. This rule is mandatory.

## Role Model

The first implementation should support these roles:

- `coding`
- `testing`
- `review` (optional in MVP but supported by the model)

`testing` and `review` are both verification roles. They are intentionally separate sessions from coding.

Minimum behavior:

- coding produces code and coding checkpoints
- testing produces verification reports and pass/fail results
- review produces acceptance findings and pass/fail results
- failed verification requests a new coding attempt

If MVP complexity must be reduced, review can be deferred and testing can be the first implemented verification role. The data model must still leave room for both.

## Worktree Model

### Why Worktree Matters

The authoritative code view for a task must remain stable across multiple attempts.

Without that stability:

- verification may inspect the wrong code
- a new coding attempt may not know where to continue
- cleanup may delete code that still matters

### Phase 1 Worktree Rules

For the first implementation:

- every coding task gets its own dedicated git worktree
- all coding attempts for that task reuse the same worktree unless the worktree is declared bad
- testing and review run against the same worktree in separate sessions
- verification must not silently allocate a different worktree for the same task

This is the required behavior for task correctness.

### Future Workspace Generalization

The internal design should preserve a later migration path from local worktrees to more general workspaces, such as:

- remote containers
- cloud-hosted repositories
- provider-specific remote workspaces

The first implementation may still use names like `worktree` in the user interface because that is the actual phase 1 behavior.

## Orchestrator Visibility Requirements

The orchestrator cannot make reliable decisions if it only sees the current session.

It must be able to inspect the full durable work record needed for scheduling and recovery.

At minimum, the orchestrator must be able to answer:

- which tasks exist
- each task's current lifecycle state
- how many attempts each task has had
- the role and outcome of each attempt
- the currently active session, if any
- the current worktree for each task
- the latest checkpoint for each task
- the latest verification result for each task
- the current blocker, if any
- the recommended next action

This does not require replaying full raw logs. It requires a stable operator snapshot projection built from durable state.

## Operator Snapshot Model

The system should maintain a derived snapshot for status commands and supervising agents.

The snapshot should include:

- workflow summary
- task summary
- latest attempt per task
- active session per task
- current worktree occupancy
- latest checkpoint summary
- latest verification result
- recommended next action
- latest error or blocker summary

The snapshot is not the source of truth. SQLite rows and repository artifacts remain authoritative. The snapshot is the decision surface.

## Durable Data Model

The following tables or equivalent storage structures are required.

### `workflows`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `project_name TEXT NOT NULL`
- `repo TEXT`
- `state TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `started_at TEXT`
- `finished_at TEXT`
- `last_error TEXT`

The workflow row should remain simple in phase 1.

### `tasks`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `workflow_id TEXT NOT NULL`
- `name TEXT NOT NULL`
- `kind TEXT NOT NULL`
- `state TEXT NOT NULL`
- `priority INTEGER`
- `worktree_id TEXT`
- `accepted_commit TEXT`
- `result_summary TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `completed_at TEXT`
- `last_error TEXT`

Suggested `kind` values:

- `feature`
- `bugfix`
- `refactor`

Suggested task states:

- `planned`
- `ready`
- `running`
- `awaiting_verification`
- `fix_requested`
- `completed`
- `failed`
- `canceled`
- `cleaned`

### `attempts`

This is a required table. It is the core execution-history table.

Suggested columns:

- `id TEXT PRIMARY KEY`
- `task_id TEXT NOT NULL`
- `role TEXT NOT NULL`
- `ordinal INTEGER NOT NULL`
- `status TEXT NOT NULL`
- `continuation_mode TEXT NOT NULL`
- `parent_attempt_id TEXT`
- `resume_from_attempt_id TEXT`
- `session_id TEXT`
- `worktree_id TEXT`
- `started_at TEXT`
- `finished_at TEXT`
- `result_summary TEXT`
- `failure_summary TEXT`
- `created_checkpoint_id TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Suggested role values:

- `coding`
- `testing`
- `review`

Suggested attempt statuses:

- `queued`
- `launching`
- `running`
- `succeeded`
- `failed`
- `timed_out`
- `canceled`

Suggested continuation modes:

- `fresh_start`
- `restart_from_checkpoint`
- `resume_same_session`

### `sessions`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `attempt_id TEXT NOT NULL`
- `runtime_adapter TEXT NOT NULL`
- `provider TEXT`
- `model TEXT`
- `session_name TEXT`
- `external_session_id TEXT`
- `host TEXT`
- `working_directory TEXT`
- `status TEXT NOT NULL`
- `supports_resume INTEGER NOT NULL DEFAULT 0`
- `last_heartbeat_at TEXT`
- `last_event_at TEXT`
- `last_event_summary TEXT`
- `runtime_meta_json TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Suggested session statuses:

- `launching`
- `running`
- `completed`
- `failed`
- `timed_out`
- `lost`

### `worktrees`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `workflow_id TEXT NOT NULL`
- `task_id TEXT NOT NULL`
- `branch TEXT NOT NULL`
- `path TEXT NOT NULL`
- `base_dir TEXT NOT NULL`
- `from_branch TEXT NOT NULL`
- `status TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `released_at TEXT`
- `cleaned_at TEXT`

Suggested worktree statuses:

- `active`
- `released`
- `cleaned`
- `failed`

### `checkpoints`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `workflow_id TEXT NOT NULL`
- `task_id TEXT NOT NULL`
- `attempt_id TEXT NOT NULL`
- `role TEXT NOT NULL`
- `checkpoint_type TEXT NOT NULL`
- `ordinal INTEGER NOT NULL`
- `artifact_path TEXT NOT NULL`
- `git_commit TEXT`
- `summary TEXT NOT NULL`
- `verification_result TEXT`
- `next_action TEXT`
- `created_at TEXT NOT NULL`

Suggested verification result values:

- `passed`
- `failed`
- `partial`
- `not_applicable`

`partial` should remain an attempt/checkpoint-level result, not a separate task lifecycle state.

### `task_dependencies`

Suggested columns:

- `task_id TEXT NOT NULL`
- `depends_on_task_id TEXT NOT NULL`
- `PRIMARY KEY (task_id, depends_on_task_id)`

### `events`

Keep or extend the existing event log. It should provide audit history, not replace the structured tables above.

Required event examples:

- task created
- attempt queued
- attempt launched
- session created
- session resumed
- session lost
- checkpoint created
- verification failed
- fix requested
- worktree created
- worktree cleaned
- merge completed

## Scheduling Model

### Scheduler Responsibilities

The scheduler must:

- find ready tasks
- create coding attempts
- create verification attempts after coding checkpoints
- route failed verification back to a new coding attempt
- avoid duplicate launches for the same task role
- update task state only from durable attempt and checkpoint outcomes

### Daemon Responsibilities

The daemon must become the single background reconciliation authority.

It must:

- reconcile active sessions
- detect clean completion, timeout, or loss
- finalize attempts
- record checkpoints
- promote task states
- start downstream verification attempts
- request fix attempts after failed verification
- update the operator snapshot

The daemon must not rely on transient process memory to understand the system.

### Required Task Transition Rules

1. When a coding attempt succeeds:
   - create a coding checkpoint
   - set task state to `awaiting_verification`
   - queue a testing attempt in a new session

2. When a testing attempt succeeds and reports pass:
   - create a verification checkpoint
   - mark task `completed`

3. When a testing attempt succeeds and reports fail or partial:
   - create a verification checkpoint
   - mark task `fix_requested`
   - queue a new coding attempt

4. When a review attempt is enabled and fails:
   - create a review checkpoint
   - mark task `fix_requested`
   - queue a new coding attempt

5. When an active coding session is lost before the next checkpoint:
   - mark the attempt failed or lost
   - keep the task open
   - queue a new coding attempt with `restart_from_checkpoint`

## Verification Rules

Verification is not optional bookkeeping. It is part of the definition of completion.

Required rules:

- coding complete does not equal task complete
- testing is always a new session
- testing must inspect the same task worktree
- failed testing creates a durable report
- failed testing reopens coding through a new coding attempt
- only a passing verification result can complete the task

If review is enabled, it follows the same session-separation rule.

## Runtime Adapter Architecture

The orchestration core must not hard-code ACP-specific behavior into task state transitions.

The runtime layer should be modular.

### Required Adapter Boundary

Introduce a runtime adapter abstraction with operations similar to:

- `launch_session(attempt, worktree, prompt_context)`
- `resume_session(session)`
- `poll_session(session)`
- `cancel_session(session)`
- `collect_terminal_summary(session)`

### Required Capability Fields

Each runtime adapter should expose capabilities such as:

- `supports_resume`
- `supports_heartbeat`
- `supports_streaming_events`
- `supports_remote_workspace`

### Phase 1 Runtime

The first implementation should use:

- local ACP-backed runtime
- local git worktrees

Suggested adapter names:

- `AcpLocalRuntimeAdapter`
- `LocalGitWorktreeAdapter`

This satisfies the immediate need while preserving the correct architectural seam for future cloud execution.

## Prompt and Execution Context Rules

Prompts must be generated from durable state, not from assumptions about old chat history.

### Coding Attempt Prompt Must Include

- task goal
- constraints
- current worktree path
- latest checkpoint summary
- latest verification report when applicable
- explicit next objective

### Testing Attempt Prompt Must Include

- task goal
- current authoritative worktree path
- latest coding checkpoint summary
- explicit instruction to verify rather than continue implementation
- required test report format

### Review Attempt Prompt Must Include

- task goal
- current authoritative worktree path
- latest coding checkpoint summary
- acceptance criteria
- explicit requirement to produce actionable findings

Testing and review prompts must not be treated as a continuation of the coding session. They are separate verification sessions driven by checkpoint handoff.

## Merge and Cleanup Policy

Merge is outside the core orchestration loop until a task is verified complete.

Rules:

- a task branch may contain multiple coding checkpoint commits
- unverified commits stay on the task branch only
- only the accepted candidate commit may be merged
- worktree cleanup must never run while a non-terminal attempt still references the worktree
- after merge, the worktree may be marked released and later cleaned

## Required Invariants

The implementation must preserve these invariants:

1. A task may have many attempts.
2. An attempt may have one session, but a session is not the unit of task history.
3. Every completed session creates a checkpoint.
4. Every coding checkpoint that changes code is committed to the task branch.
5. Testing always runs in a new session.
6. Testing and review inspect the same authoritative task worktree.
7. Task completion requires passing verification, not merely coding completion.
8. The orchestrator can recover from session loss using the latest checkpoint.
9. Worktree cleanup cannot delete a worktree still referenced by active work.
10. The operator snapshot can be reconstructed from durable state plus runtime inspection.

## Backward Compatibility

The simple path must continue to work:

- one task
- one coding worktree
- one coding session
- one checkpoint after coding completion

But the implementation must internally move toward the checkpoint-first model even for the simple path.

The user-facing CLI can preserve commands such as:

- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

Under the hood, those commands should operate on workflow, task, attempt, session, worktree, and checkpoint state rather than the old single-session task assumptions.

## Implementation Guidance for Coding Agents

Implement this refactor in phases. Do not attempt a single large rewrite.

### Phase 1: Add durable primitives

- add workflow, task, attempt, session, worktree, and checkpoint schema support
- keep legacy task rows readable during migration
- add serializers and typed models

### Phase 2: Introduce checkpoint creation

- create checkpoint records and repository artifacts for completed sessions
- create code commits for coding checkpoints
- add status rendering for latest checkpoint

### Phase 3: Split attempt and session lifecycle

- make attempts first-class
- track session metadata separately
- distinguish fresh start, resume, and restart from checkpoint

### Phase 4: Enforce verification loop

- coding success must queue testing
- testing must always start a new session
- failed testing must route back to coding

### Phase 5: Add modular runtime adapters

- keep ACP local as the first implementation
- move runtime-specific logic behind adapter boundaries

### Phase 6: Improve status and operator surfaces

- add attempt history to status
- expose active worktrees
- expose latest checkpoint and next action

## Testing Requirements

The implementation must add or update tests in these areas.

### Schema and Model Tests

- workflow, task, attempt, session, worktree, and checkpoint round-trip persistence
- compatibility reads for legacy task rows

### Checkpoint Tests

- completed coding session creates a checkpoint artifact
- completed coding session that changed code creates a commit reference
- completed testing session creates a verification checkpoint

### Lifecycle Tests

- coding completion queues testing
- testing always launches a new session
- failed testing requests a new coding attempt
- lost session triggers restart from latest checkpoint

### Worktree Tests

- coding task gets a dedicated worktree
- testing reuses the coding worktree
- cleanup refuses to remove worktree while active attempts still reference it

### Status Tests

- status surfaces show task state, latest attempt, current session, current worktree, latest checkpoint, and next action

### Adapter Tests

- ACP local adapter launches and polls sessions
- runtime adapter capabilities influence scheduling choices

## Acceptance Criteria

This refactor is complete when all of the following are true:

1. A project with multiple tasks can be represented durably.
2. A task can survive more than one coding and testing cycle.
3. Coding completion creates a checkpoint but does not complete the task.
4. Testing always starts in a new session.
5. Failed testing triggers a new coding attempt from the latest checkpoint.
6. A lost coding session can be replaced by a new session without losing the task.
7. Worktree reuse for verification is enforced.
8. Operators can inspect the complete durable work record needed for orchestration.
9. The first implementation works locally with ACP.
10. The architecture preserves a clean path to future runtime plugins.

## Final Rule

If an implementation choice is ambiguous, prefer the option that makes the system easier to recover after a crash, easier to inspect from durable state, and easier for a fresh coding session to continue from the latest checkpoint.

That is the core of this design.
