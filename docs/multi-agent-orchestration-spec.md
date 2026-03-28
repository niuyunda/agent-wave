# Multi-Agent Orchestration Refactor Spec

## Document Purpose

This document is an implementation specification for coding agents modifying `agent-wave` (`agvv`).

Follow this spec to evolve `agvv` from a single-task runner into a workflow-oriented orchestrator that can:

- run multiple coding tasks in parallel
- assign isolated git worktrees per coding task
- track worker roles such as coding, test, and review
- route failures back to the original coding worker
- preserve durable state for retries, auditing, and cleanup

This document is intentionally operational. It defines target behavior, data model changes, state transitions, implementation boundaries, and rollout order.

## Current System Summary

Today, `agvv` is a lightweight task runner:

- one task creates or attaches one feature worktree
- one task launches one ACP coding session
- one task stores one current session in SQLite
- one daemon loop reconciles `pending` and `running` tasks

Current behavior is documented in `README.md` and implemented mainly in:

- `agvv/runtime/models.py`
- `agvv/runtime/store.py`
- `agvv/runtime/core.py`
- `agvv/runtime/session_lifecycle.py`
- `agvv/runtime/dispatcher.py`
- `agvv/orchestration/layout.py`
- `agvv/orchestration/acp_ops.py`

This architecture is correct for "one task, one worker, one worktree". It is not sufficient for multi-agent orchestration.

## Problem Statement

The current data model conflates these concerns:

- task identity
- feature branch identity
- worktree allocation
- worker role
- ACP session identity
- retry history

As a result, the current system cannot model the following well:

- a coding worker finishes and a test worker starts on the same worktree
- a test worker fails and the system resumes or reassigns the original coding worker
- multiple coding workers run in parallel on different worktrees for one higher-level workflow
- review, test, and fix cycles are represented durably rather than inferred from logs
- one task has more than one session attempt over time

The refactor must separate workflow, task, attempt, session, and worktree concerns.

## Design Goals

Every change in this refactor must improve at least one of these:

- isolation
- reliability
- recoverability
- observability
- orchestration clarity

The resulting system must:

- keep isolated worktrees as a first-class primitive
- preserve explicit session lineage across retries and fix requests
- make all state transitions durable in SQLite
- load repository-owned workflow policy from a checked-in contract file
- support role-specific workers
- support dependency-aware scheduling
- expose a coherent operator snapshot for status and debugging
- remain usable for the simple case of a single coding task

## Non-Goals

This refactor must not attempt the following in the first implementation:

- general DAG scheduling across arbitrary external systems
- automatic Git merge conflict resolution
- autonomous branch deletion or force recovery after ambiguous worktree failures
- provider-specific prompt engineering beyond basic role templates
- replacing ACP with a separate runtime

## Repository Workflow Contract

`agent-wave` should not encode all orchestration behavior only in Python code and ad hoc CLI flags.

Add a repository-owned workflow contract file. A default file such as `WORKFLOW.md` is preferred because it can carry both structured configuration and prompt templates in one checked-in artifact.

The workflow contract should define:

- workflow-level defaults
- role-specific prompt templates
- role sequencing policy
- optional dependency templates
- verification and review requirements
- ACP/runtime defaults
- worktree bootstrap or validation hooks when needed

The workflow contract must be:

- versioned with the repository
- reloadable without changing durable workflow history semantics
- visible to coding agents as the policy source of truth
- optional for legacy single-task usage, with safe defaults when omitted

### Suggested contract shape

The contract may use YAML front matter plus markdown prompt bodies, or a dedicated YAML/TOML file if the implementation prefers strict parsing.

At minimum it should be able to express:

- `roles.coding.prompt_template`
- `roles.test.prompt_template`
- `roles.review.prompt_template`
- `scheduler.require_review`
- `scheduler.require_test`
- `scheduler.auto_create_review_task`
- `scheduler.auto_create_test_task`
- `runtime.agent_provider`
- `runtime.agent_model`
- `runtime.max_concurrent_attempts`
- `worktree.bootstrap`

### Contract precedence

Use this precedence order:

1. explicit CLI override
2. workflow contract file
3. built-in defaults

The resolved contract used for a workflow should be recorded durably, at minimum by storing a digest and the resolved spec JSON on the workflow row.

## Target Architecture

The target model has five distinct concepts:

1. `Workflow`
2. `Task`
3. `Attempt`
4. `WorktreeLease`
5. `SessionBinding`

### Workflow

A workflow is the top-level orchestration unit. It represents a larger unit of work that may contain multiple tasks or steps.

Examples:

- implement two features and one refactor for one repository
- fix a bug, run tests, and merge after green

### Task

A task is a schedulable unit of business work. It is not the same thing as a session and not always the same thing as a worktree.

Examples:

- implement feature A
- implement feature B
- refactor component C
- run browser E2E on feature A
- review coding result for feature B

### Attempt

An attempt is one execution of one worker against one task.

Examples:

- coding attempt #1 for feature A
- test attempt #1 for feature A
- coding fix attempt #2 for feature A after failed tests

Attempts are the proper home for session identity, runtime status, and retry lineage.

### WorktreeLease

A worktree lease is a durable record for an allocated worktree resource.

It owns:

- branch name
- filesystem path
- lifecycle status

Tasks and attempts may reference a worktree lease. Not every task creates its own lease.

### SessionBinding

A session binding represents the runtime identity associated with an attempt.

For ACP-backed workers this includes:

- provider
- normalized agent command
- session name
- session id when available
- working directory
- resumability metadata
- worker host when relevant
- last known runtime phase
- last heartbeat timestamp
- last event timestamp and summary
- snapshot-ready runtime metadata

## High-Level Behavioral Model

The desired execution loop is:

1. create workflow
2. create tasks and dependency edges
3. scheduler selects ready tasks
4. scheduler chooses worker role and worktree strategy
5. scheduler creates an attempt
6. runtime launches or resumes an ACP session for that attempt
7. daemon reconciles attempt runtime state
8. terminal attempt updates the owning task state
9. scheduler creates downstream tasks or follow-up attempts
10. workflow completes only after all required tasks reach terminal success

## Operator Snapshot Model

The system must expose a coherent runtime snapshot for operators and supervising agents.

This snapshot is a derived read model. It is not the source of truth. SQLite rows remain authoritative, but status commands and dashboards should read from a stable projection rather than reimplementing orchestration logic in presentation code.

At minimum the snapshot should include:

- workflow summary
- task summary
- latest attempt per task
- currently running attempts
- retrying or backoff attempts
- worktree lease occupancy
- current session binding metadata
- latest event and error summary
- recommended next action

### Snapshot requirements

- status surfaces must be able to answer "what is running now" without scanning raw event logs
- the snapshot must make role, lineage, and lease reuse visible
- the snapshot must degrade safely when runtime polling is temporarily stale
- the snapshot must be reconstructable after process restart from durable state plus current runtime inspection

## Data Model Refactor

## Existing Tables

Keep the existing `tasks`, `task_events`, and `task_reconcile_locks` tables for compatibility and migration support.

However, the meaning of `tasks` must evolve.

## New Core Tables

Add the following tables.

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
- `spec_json TEXT NOT NULL`
- `workflow_contract_path TEXT`
- `workflow_contract_digest TEXT`

Suggested states:

- `planned`
- `running`
- `completed`
- `failed`
- `timed_out`
- `canceled`
- `cleaned`

### `tasks`

Retain the table name but change its semantic role.

Suggested additional columns:

- `workflow_id TEXT NOT NULL`
- `role TEXT NOT NULL`
- `kind TEXT NOT NULL`
- `parent_task_id TEXT`
- `worktree_lease_id TEXT`
- `depends_on_count INTEGER NOT NULL DEFAULT 0`
- `state TEXT NOT NULL`
- `result_summary TEXT`
- `accepted_at TEXT`
- `merged_at TEXT`

Suggested role values:

- `coding`
- `test`
- `review`

Suggested kind values:

- `feature`
- `bugfix`
- `refactor`
- `verification`
- `review`

Suggested task states:

- `planned`
- `ready`
- `running`
- `awaiting_review`
- `awaiting_test`
- `fix_requested`
- `completed`
- `merged`
- `failed`
- `timed_out`
- `canceled`
- `cleaned`

### `task_attempts`

This is the most important new table.

Suggested columns:

- `id TEXT PRIMARY KEY`
- `task_id TEXT NOT NULL`
- `role TEXT NOT NULL`
- `ordinal INTEGER NOT NULL`
- `status TEXT NOT NULL`
- `agent_provider TEXT`
- `agent_model TEXT`
- `agent_cmd TEXT`
- `session_name TEXT`
- `session_id TEXT`
- `worktree_lease_id TEXT`
- `worktree_path TEXT`
- `resume_from_attempt_id TEXT`
- `parent_attempt_id TEXT`
- `started_at TEXT`
- `finished_at TEXT`
- `last_error TEXT`
- `result_summary TEXT`
- `launch_meta_json TEXT`
- `runtime_meta_json TEXT`
- `worker_host TEXT`
- `last_heartbeat_at TEXT`
- `last_event_at TEXT`
- `last_event_type TEXT`
- `last_event_summary TEXT`
- `runtime_snapshot_json TEXT`

Suggested attempt statuses:

- `queued`
- `launching`
- `running`
- `succeeded`
- `failed`
- `timed_out`
- `canceled`

### `worktree_leases`

Suggested columns:

- `id TEXT PRIMARY KEY`
- `workflow_id TEXT NOT NULL`
- `project_name TEXT NOT NULL`
- `feature TEXT NOT NULL`
- `branch TEXT NOT NULL`
- `worktree_path TEXT NOT NULL`
- `base_dir TEXT NOT NULL`
- `from_branch TEXT NOT NULL`
- `status TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `released_at TEXT`
- `cleaned_at TEXT`
- `metadata_json TEXT`

Suggested statuses:

- `active`
- `released`
- `cleaned`
- `failed`

### `task_dependencies`

Suggested columns:

- `task_id TEXT NOT NULL`
- `depends_on_task_id TEXT NOT NULL`
- `PRIMARY KEY (task_id, depends_on_task_id)`

This provides explicit scheduling dependencies instead of inferring order from task state names.

## Compatibility Strategy

Do not remove legacy columns immediately.

Use a compatibility approach:

1. Add new tables and columns.
2. Populate both old and new representations during a transition period.
3. Move daemon and CLI reads onto the new tables.
4. Keep legacy fields only until migration safety is proven.

The first implementation should prefer additive migration over destructive migration.

## Workflow Contract Loading

Add a workflow loader/store layer similar in spirit to a config cache:

- resolve the current workflow contract path
- parse and validate it
- retain the last known good contract for runtime use
- expose typed accessors for scheduler and prompt generation

Required behavior:

- invalid contract changes must not corrupt running workflows
- contract reload errors should be visible in status and logs
- the workflow row should record the digest of the resolved contract used at creation time
- workflows already created should not silently change semantics mid-run unless an explicit "reload policy" allows it

## Worktree Model

## Required Behavior

The system must support two worktree strategies:

### Strategy A: dedicated coding worktree

Use for primary implementation tasks.

Behavior:

- allocate a new feature branch and worktree lease
- create worktree at `worktrees/<slug>/`
- bind the lease to the coding task
- bind coding attempts to the same lease

### Strategy B: shared verification worktree

Use for review and test tasks that must validate coding output in-place.

Behavior:

- reuse the worktree lease of the target coding task
- do not create a second branch or second worktree by default
- preserve the exact filesystem view that the coding worker used

## Required Changes

`agvv/orchestration/layout.py` already has strong worktree lifecycle primitives. Keep them, but stop treating them as task-only behavior.

Required refactor:

- extract lease-aware functions from `start_feature()` and cleanup helpers
- add explicit "create lease", "attach lease", "release lease", and "cleanup lease" APIs
- preserve `context.json`, but add durable linkage to `worktree_leases`

### New layout API shape

Add functions with behavior similar to:

- `create_worktree_lease(...)`
- `attach_existing_worktree_lease(...)`
- `cleanup_worktree_lease(...)`
- `ensure_worktree_metadata(...)`

Avoid automatic destructive recovery if branch or worktree conflict is ambiguous.

## Session Model

## Current Problem

`agvv` currently stores one session on the task and treats retry as another launch of the same task session.

This is insufficient for:

- resuming the original coding worker after test failure
- keeping coding and test sessions separate
- auditing multiple attempts

## Target Session Rules

### For coding attempts

- prefer reusing the same worktree lease
- prefer resuming the original session when the provider/runtime can support it
- if resume is not possible, create a new session but preserve linkage to the prior attempt

### For test attempts

- create a new attempt
- use the same worktree lease as the target coding task
- use a distinct session
- never overwrite the coding attempt's session identity

### For review attempts

- same rules as test attempts
- allow review to be purely observational

## Runtime Update Model

The orchestrator must treat runtime updates as first-class input, not as log text to be interpreted later.

Attempts should receive live runtime updates when available, including:

- session started
- prompt sent
- heartbeat
- notification or tool event summary
- token usage or cost summary when available
- terminal completion event
- runtime failure event

Required behavior:

- update the latest attempt runtime fields during execution
- preserve only compact summaries in primary attempt rows
- store detailed runtime events in `task_events` or a dedicated attempt-event table
- allow status output to show the latest known runtime phase and message without opening raw logs

If the runtime does not support rich streaming events, fall back to heartbeat plus polling-based summaries.

## Runtime Lifecycle Refactor

## Current Problem

`agvv/runtime/session_lifecycle.py` launches ACP in a blocking way. `acpx_send_prompt()` waits for completion. This is appropriate for a single synchronous task runner but incorrect for a real orchestrator.

## Required Behavior

Launching a worker must become a two-phase process:

1. session bootstrap
2. asynchronous execution monitoring

### Phase 1: bootstrap

Bootstrap must:

- resolve worktree path
- create launch artifacts
- create or reuse ACP session identity
- create an attempt row
- record session metadata on the attempt
- return immediately with attempt status `running` or `launching`

### Phase 2: reconcile

Daemon reconciliation must:

- poll ACP session state
- detect completion, timeout, or death
- capture output summary and metadata
- transition attempt state
- trigger downstream task scheduling

## Required Changes

Refactor `agvv/runtime/session_lifecycle.py` to separate:

- `prepare_attempt_launch(...)`
- `start_or_resume_acp_session(...)`
- `reconcile_attempt_runtime(...)`
- `finalize_attempt(...)`

`agvv/orchestration/acp_ops.py` must stop being treated as a single blocking command runner.

Add APIs for:

- create session if missing
- inspect session
- send prompt without collapsing attempt lineage
- capture stable session id
- soft close
- hard delete

Do not require `task run` or `task retry` to block until worker completion.

## Continuation and Fresh-Start Policy

The scheduler must distinguish between three follow-up modes:

1. `resume_same_session`
2. `new_attempt_same_lineage`
3. `fresh_lineage`

### `resume_same_session`

Use when:

- the prior coding session still exists
- the runtime can resume safely
- the worktree lease is healthy
- the task is in a fix or continuation loop

### `new_attempt_same_lineage`

Use when:

- the prior session cannot be resumed
- the original coding lineage should remain the owner of the task
- the same worktree lease should be reused

This is the default fallback for fix requests.

### `fresh_lineage`

Use only when:

- the prior lineage is invalid or unrecoverable
- the worktree lease is corrupt, ambiguous, or explicitly replaced
- the workflow policy requires a clean restart

Fresh lineage creation must be explicit in durable state and visible in status output. It must not happen silently during ordinary retry handling.

## Scheduler Refactor

## Current Problem

`agvv/runtime/dispatcher.py` only supports:

- `pending -> launch`
- `running -> done or timed_out`

It does not schedule downstream tasks or make dependency decisions.

## Required New Scheduler

Add a workflow scheduler module, for example:

- `agvv/runtime/workflow_scheduler.py`

Responsibilities:

- find `ready` tasks with satisfied dependencies
- choose worktree strategy based on task role
- create attempts
- launch attempts
- update task state based on latest attempts
- schedule review and test tasks after coding completion
- schedule fix attempts after failed verification

## Scheduling Rules

### Rule 1: coding task completion

When a coding attempt succeeds:

- if review is required, transition task to `awaiting_review`
- if no review is required, transition task to `awaiting_test`
- create dependent review/test tasks when configured

### Rule 2: review success

- transition owning task to `awaiting_test`
- create or unlock test task

### Rule 3: review failure

- transition owning task to `fix_requested`
- create a new coding attempt linked to the latest coding attempt

### Rule 4: test success

- transition owning task to `completed`

### Rule 5: test failure

- transition owning task to `fix_requested`
- create a fix attempt for the original coding worker lineage

## Attempt Routing Rules

When `fix_requested` occurs, the system must route the next coding attempt to the original coding lineage.

Resolution algorithm:

1. find the latest coding attempt for the task that reached `running` or `succeeded`
2. if its session is resumable and still exists, resume it
3. otherwise create a new coding attempt with:
   - the same worktree lease
   - `resume_from_attempt_id` set to the original coding attempt
   - the same preferred provider unless explicitly overridden

Never route a fix request to the latest test attempt.

## Prompting Requirements

The system must support role-specific prompts sourced from the workflow contract.

### Coding role prompt

Must include:

- task requirements
- constraints
- branch/worktree context
- explicit instruction to modify code and tests as needed

### Test role prompt

Must include:

- target coding task summary
- worktree to inspect
- explicit instruction to validate behavior, not implement unrelated changes
- expected artifacts such as logs, failing cases, reproduction details

### Review role prompt

Must include:

- target coding task summary
- review scope
- acceptance checklist
- explicit requirement to produce actionable findings

Role prompts should be generated centrally, not embedded ad hoc in CLI commands.

### Prompt rendering rules

- prompt templates should be resolved from the workflow contract
- prompt rendering should receive structured task, attempt, workflow, and worktree context
- retry and continuation mode must be explicit in the rendered prompt
- prompt generation must not be the only place where orchestration decisions exist; rendered prompts reflect state, they do not define it

## CLI Changes

## Preserve Existing Commands

Keep these working for backward compatibility:

- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

## Extend Semantics

### `task run`

Continue to support the single-task case, but internally:

- create a workflow if needed
- create one coding task
- create one initial coding attempt

### `task status`

Must be expanded to show:

- task state
- latest attempt status
- worker role
- session info
- worktree lease
- last error
- last runtime event
- continuation mode or next action recommendation

Optionally add:

- `--attempts`
- `--events`

### `task retry`

Current `retry` is too generic.

Split behavior internally into:

- retry the latest failed attempt
- request a fix on the coding lineage

Backward-compatible CLI behavior may remain, but implementation must distinguish:

- retry same role
- route back to coding role

### New commands

Add workflow-oriented commands after the model is stable:

- `agvv workflow run`
- `agvv workflow status`
- `agvv workflow cleanup`

These are not required in phase 1, but the internal architecture must not block them.

### Snapshot-oriented status surface

Expose a status surface that reads from the operator snapshot model.

This may initially be:

- richer CLI text output
- `--json` status output

Later it may also power:

- a small dashboard
- supervising-agent integration
- event subscriptions

## Event and Audit Model

Keep `task_events`, but start treating events as workflow-relevant.

Required event types include:

- task created
- attempt queued
- attempt launched
- ACP session created
- ACP session resumed
- attempt completed
- attempt failed
- timeout detected
- downstream task scheduled
- fix requested
- worktree lease created
- worktree lease cleaned
- runtime heartbeat recorded
- runtime snapshot refreshed
- continuation mode selected
- fresh lineage created

Event metadata must contain stable identifiers:

- `workflow_id`
- `task_id`
- `attempt_id`
- `worktree_lease_id`
- `session_name`
- `session_id`

## Daemon Behavior

The daemon must become the single source of truth for background reconciliation.

### Required daemon loop responsibilities

- reconcile active attempts
- detect terminal session outcomes
- update task state
- release or retain worktree leases according to policy
- create downstream attempts for ready tasks
- respect dependency edges
- refresh the operator snapshot projection
- surface workflow contract load failures

### Concurrency rules

The daemon may reconcile multiple active attempts in parallel, but must prevent duplicate scheduling.

Use:

- per-task locks for task state transitions
- per-attempt locks for session reconciliation
- workflow-safe ordering for downstream scheduling

Do not allow two workers to be launched simultaneously for the same task role unless explicitly configured.

## Migration Plan

Implement in phases.

### Phase 1: additive schema

- add new tables
- add compatibility read/write helpers
- keep old commands functional

### Phase 2: attempt-aware launches

- write attempt rows for all launches
- store session metadata on attempts
- keep task-level session fields for compatibility only

### Phase 3: scheduler split

- move attempt lifecycle reconciliation out of the task-only dispatcher
- add workflow-aware scheduling

### Phase 4: role-aware orchestration

- support coding/test/review roles
- support dependency edges
- support fix routing to original coding lineage

### Phase 5: CLI and docs alignment

- update README
- update SKILL.md
- add examples for single-task and multi-task workflows

### Phase 6: contract-aware prompts and richer status surfaces

- load workflow contract from the repository
- render role prompts from the contract
- expose snapshot-driven status output

## Required Invariants

The implementation must preserve these invariants.

### Invariant 1

One coding attempt writes to exactly one active worktree lease.

### Invariant 2

Review and test attempts must not silently allocate a new worktree when they are intended to validate an existing coding result.

### Invariant 3

Every attempt has durable lineage to:

- one task
- zero or one parent attempt
- zero or one resume source attempt

### Invariant 4

A task must not be considered `completed` only because an ACP session ended. It is `completed` only when the required workflow role sequence succeeds.

### Invariant 5

Cleanup must not delete a worktree lease still referenced by any non-terminal attempt.

### Invariant 6

The workflow contract used to create a workflow must be identifiable after restart by path and digest.

### Invariant 7

A fix request must not silently create a fresh lineage when resuming or same-lineage continuation is still safe.

### Invariant 8

Operator status must be derivable from durable state plus current runtime inspection without replaying the full raw transcript.

## Backward Compatibility Requirements

The simple path must continue to work:

- one `task.md`
- one coding worker
- one worktree
- one session
- one cleanup

The user must not be forced to adopt workflow-level commands for the basic use case.

## Testing Requirements

Add or update tests in these areas.

### Model and schema tests

- workflow/task/attempt/lease serialization
- migrations from old schema to new schema
- workflow contract parse and validation tests

### Worktree lifecycle tests

- dedicated coding worktree allocation
- verification task reuses coding worktree
- cleanup refuses deletion when lease is still referenced

### Session lifecycle tests

- launch creates attempt and session metadata
- reconcile marks attempt success when ACP session ends cleanly
- timeout marks attempt timed out
- retry creates a new attempt while preserving lineage
- runtime updates refresh attempt heartbeat and latest event fields

### Scheduler tests

- coding success unlocks review or test
- test failure creates fix request
- fix request routes to coding lineage rather than test lineage
- dependencies prevent premature launch
- continuation policy chooses resume, same-lineage retry, or fresh lineage correctly

### CLI tests

- legacy `task run/status/retry/cleanup` still function
- expanded status output includes attempt and lease data
- status snapshot output includes runtime event summary and next action

### Observability tests

- snapshot projection is consistent with durable state
- degraded runtime inspection still produces safe status output
- workflow contract reload failure is surfaced without corrupting active workflows

## Acceptance Criteria

This refactor is complete when all of the following are true.

1. A single coding task still works with `agvv task run`.
2. The database records multiple attempts for one task.
3. Review and test attempts can run against an existing coding worktree.
4. A failed test can trigger a follow-up coding attempt on the original coding lineage.
5. The daemon can reconcile multiple active attempts safely.
6. Cleanup respects active lease references.
7. Status commands show enough information to identify:
   - which worker ran
   - which session was used
   - which worktree lease was used
   - whether the next action is review, test, fix, or cleanup
8. The workflow used for a run is identifiable by contract path and digest.
9. Runtime status surfaces can show the latest attempt event and whether a fix will resume the same lineage or start a fresh one.

## Definition of Done

This refactor is done only when all of the following are true.

### Product and behavior

- the single-task path still works without requiring workflow-specific input
- the new workflow model supports multiple tasks and multiple attempts durably
- coding, review, and test roles are distinguishable in both state and status output
- failed verification can be routed back to the original coding lineage
- cleanup behavior is safe and lease-aware

### Data and migration

- schema migrations run cleanly from the current production schema
- old task rows remain readable after migration
- new rows persist enough metadata to reconstruct task, attempt, session, and lease lineage
- no required runtime behavior depends only on logs or transient process memory
- the workflow contract used for a workflow is recorded durably

### Runtime and scheduling

- attempt launch is no longer modeled as a single blocking task execution step
- the daemon can reconcile more than one active attempt in one pass
- dependency and readiness transitions are persisted durably
- retry, fix, and resume paths preserve lineage explicitly
- runtime updates refresh snapshot-visible attempt state during execution

### Operator experience

- `task run`, `task status`, `task retry`, and `task cleanup` still work for the basic case
- status output is sufficient for an operator to determine the current owner, current runtime state, and next action
- status output identifies the active workflow contract and the latest runtime event summary
- failure messages are actionable and identify whether the issue is schema, scheduling, worktree, ACP runtime, or cleanup related

### Verification

- tests for touched areas exist and pass
- backward compatibility behavior is covered by tests, not assumed
- README and operator-facing docs are updated to match the shipped behavior

## Engineering Implementation Checklist

Use the following commit plan unless a concrete code-level constraint requires a local reordering. Each commit should keep the repository in a working state and include the most direct tests for the touched surface.

### Commit 1: Add schema primitives and compatibility migration

Scope:

- add new tables for `workflows`, `task_attempts`, `worktree_leases`, and `task_dependencies`
- add new columns needed on `tasks`
- add workflow contract path and digest storage
- keep old rows readable and preserve compatibility with existing task commands
- add migration helpers and version detection

Expected files:

- `agvv/runtime/store.py`
- `agvv/runtime/models.py`
- migration helpers or schema utilities if split out

Required checks:

- schema migration tests
- round-trip persistence tests for new tables
- compatibility test that older task rows remain readable

Exit condition:

- a migrated database can represent workflow, task, attempt, and lease state without breaking legacy reads

### Commit 2: Add workflow contract loading and typed policy access

Scope:

- load a repository-owned workflow contract
- validate contract structure and defaults
- expose typed accessors for prompt generation and scheduler policy
- persist the resolved contract identity on workflow creation

Expected files:

- workflow loader/store modules
- `agvv/runtime/core.py`
- config or validation helpers

Required checks:

- contract parse tests
- contract validation tests
- workflow creation test proving contract digest persistence

Exit condition:

- workflows can resolve policy from a checked-in contract instead of only from CLI defaults

### Commit 3: Refactor state enums and domain models

Scope:

- separate workflow state, task state, and attempt status
- add first-class role, kind, lineage, lease references, and runtime summary fields in the model layer
- stop treating task-level session metadata as the source of truth

Expected files:

- `agvv/runtime/models.py`
- `agvv/runtime/core.py`
- any shared typing or serializer modules

Required checks:

- model serialization tests
- state transition unit tests for new enums and validation helpers

Exit condition:

- code can represent multiple attempts per task without relying on overloaded task fields

### Commit 4: Introduce attempt-aware session lifecycle

Scope:

- split ACP lifecycle into session bootstrap and later reconciliation
- create attempt records before launch
- store session binding on attempts instead of relying on one task-level session field
- preserve resume and retry lineage
- capture live runtime update summaries on attempts

Expected files:

- `agvv/runtime/session_lifecycle.py`
- `agvv/orchestration/acp_ops.py`
- `agvv/runtime/core.py`

Required checks:

- session bootstrap tests
- reconcile tests for clean completion, failure, and timeout
- retry lineage tests

Exit condition:

- one task can have multiple attempts over time, and each attempt has durable runtime metadata

### Commit 5: Promote worktree leases to a first-class resource

Scope:

- wrap current worktree allocation in a lease model
- allow coding attempts to allocate leases and verification attempts to reuse them
- prevent cleanup of leases still referenced by non-terminal attempts

Expected files:

- `agvv/orchestration/layout.py`
- `agvv/runtime/store.py`
- `agvv/runtime/core.py`

Required checks:

- worktree allocation tests
- reuse tests for test and review attempts
- cleanup safety tests

Exit condition:

- worktree ownership and cleanup are enforced by lease state rather than task naming conventions alone

### Commit 6: Split dispatcher into reconcile and scheduling responsibilities

Scope:

- keep reconciliation logic explicit
- add workflow-aware readiness evaluation
- unlock downstream work based on dependencies and task state
- avoid launching verification work prematurely

Expected files:

- `agvv/runtime/dispatcher.py`
- new scheduler module if introduced
- `agvv/runtime/core.py`

Required checks:

- readiness evaluation tests
- dependency gating tests
- multi-attempt reconcile tests

Exit condition:

- the daemon can decide what is ready to run next using durable workflow state

### Commit 7: Add role-aware review, test, and fix routing

Scope:

- implement role-specific behavior for `coding`, `review`, and `test`
- route failed review or test outcomes back to the correct coding lineage
- support follow-up coding attempts on the same lease when appropriate

Expected files:

- scheduler or routing modules
- `agvv/runtime/core.py`
- prompt/template modules if they exist

Required checks:

- coding success to review or test transition tests
- test failure to fix routing tests
- lineage preservation tests

Exit condition:

- failed verification no longer dead-ends and can trigger a correct coding follow-up attempt

### Commit 8: Add snapshot-driven status surfaces and documentation

Scope:

- expose workflow, attempt, and lease information in status commands
- expose workflow contract identity and latest runtime event summary
- implement a stable operator snapshot projection
- preserve legacy commands for the simple case
- document single-task and workflow-oriented usage

Expected files:

- CLI command modules
- `README.md`
- operator docs

Required checks:

- CLI status tests
- snapshot projection tests
- backward compatibility tests for legacy commands
- smoke test for simple `task run/status/retry/cleanup`

Exit condition:

- operators can understand current workflow state without reading SQLite directly

## Commit-Level Guardrails

Apply these rules to every commit in the checklist above.

- do not mix schema, runtime, CLI, and docs churn in one giant patch if a smaller checkpoint is possible
- each commit must leave tests green for the touched scope
- do not remove compatibility shims until the replacement path is covered by tests
- do not rewrite worktree logic outside the existing orchestration boundary without a clear reason
- do not encode orchestration state only in prompt text or ACP transcript output
- prefer additive fields and tables over destructive renames in early commits

## Testing Placement Guidance

Testing requirements belong in the spec and also apply during implementation.

Keep both layers:

- the spec defines what categories of tests must exist so coding agents do not under-test the refactor
- each implementation commit defines the narrow checks that must pass before moving to the next commit

Do not defer test strategy entirely to implementation time. If tests are only decided ad hoc during coding, backward compatibility and migration coverage are likely to be missed.

Use this split:

- spec-level testing requirements define coverage expectations, migration safety, and acceptance coverage
- implementation-time checks define the exact test files, commands, and new fixtures added for the current patch

For this project, that means the current `Testing Requirements` section should stay in this document, and each commit above should carry its own direct checks.

## Implementation Order

Follow this order unless a blocking constraint appears.

1. add schema and storage primitives
2. refactor models and state enums
3. introduce attempt-aware session lifecycle
4. introduce worktree lease layer
5. split scheduler responsibilities
6. add worker roles and dependency routing
7. update CLI output and docs
8. remove obsolete task-level assumptions only after compatibility is proven

## Explicit Guidance for Coding Agents

While implementing this spec:

- do not rewrite the entire project in one pass
- prefer additive migrations over destructive changes
- preserve existing CLI behavior unless this spec explicitly changes it
- keep worktree lifecycle logic centralized
- keep ACP runtime logic centralized
- do not hide orchestration decisions in prompt text alone; persist them in SQLite
- make every state transition auditable by event records

If a choice is ambiguous, prefer the design that makes retries, auditing, and worker lineage easier to reason about.
