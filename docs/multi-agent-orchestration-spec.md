# Checkpoint-First Project Orchestration Spec

## Purpose

This document is the implementation specification for coding agents modifying `agent-wave`
(`agvv`).

It defines how `agvv` should evolve from a single-task local runner into a project-oriented
orchestrator that can:

- accept work from multiple sources
- normalize that work into durable internal records
- launch multiple agent runs in parallel
- survive session crashes and workspace failures
- continue work from repository checkpoints instead of chat history
- expose a project-level operator view for scheduling and debugging

This spec is written for coding agents. It is intentionally explicit and implementation-oriented.
An agent should be able to implement the target design from this file alone, without relying on
prior chat context.

## Design Summary

The target system is **project-driven**, **checkpoint-first**, and **run-aware**.

The essential design choices are:

1. The top-level scheduling unit is a `Project`, not a single task run.
2. All external work is normalized into `WorkItem` records.
3. The only execution primitive is a `Run`.
4. `verification` is not a separate system entity. It is only a run purpose, described in the run
   brief.
5. A `Workspace` is an execution environment, usually a git worktree in the first implementation.
6. A `Checkpoint` is the repository-backed continuity mechanism between runs.
7. A `ProjectSnapshot` is a derived global view used by the orchestrator and status surfaces.

The main correctness rule is:

**A later run must be able to continue from durable repository checkpoints plus durable runtime
metadata, even if it has no access to earlier chat history and even if the earlier runtime session
is gone.**

Resuming the same runtime session is allowed only as an optimization. It must never be a
correctness dependency.

## First-Principles Problem Statement

The current `agvv` model assumes:

- one task
- one worktree
- one coding session
- one terminal completion path

That is too small for real orchestration.

In real use:

- one project may contain multiple work items
- new work items may arrive over time
- each work item may require multiple runs
- different runs may have different purposes such as implementation, testing, review, repair, or
  analysis
- any session may stall, fail, or disappear
- any workspace may become unreliable
- the orchestrator still needs enough durable context to continue safely

From first principles, the orchestrator must always be able to answer these questions:

1. What work exists for this project?
2. What has been attempted for each work item?
3. What repository state is currently authoritative for each work item?
4. What checkpoint should the next run read before acting?
5. What is the current project-wide status and recommended next action?

If those answers cannot be recovered from durable data and repository artifacts, the system is not
yet reliable.

## What This Spec Optimizes For

Every implementation choice should improve at least one of:

- isolation
- recoverability
- auditability
- observability
- implementation clarity
- compatibility with the existing local-first `agvv` runtime

## Non-Goals

The first implementation must not attempt:

- general DAG orchestration across arbitrary external systems
- autonomous merge conflict resolution
- automatic destructive recovery after ambiguous git state
- replacing ACP in phase 1
- requiring a cloud runtime in phase 1
- building a generic workflow engine before the local checkpoint-first model is stable

## High-Level Architecture

The target system has two durable layers and one derived layer.

### Layer 1: Runtime Truth

Stored in SQLite.

This layer contains:

- projects
- input records
- work items
- runs
- agent sessions
- workspaces
- checkpoint metadata
- structured events

This layer is the durable scheduler truth.

### Layer 2: Repository Continuity

Stored in the repository as checkpoint documents plus corresponding commits.

This layer contains:

- what a run accomplished
- what code state it operated on
- what remains to be done
- what the next run should do

This layer is the continuity truth for new runs.

### Layer 3: Project Snapshot

Derived from runtime truth plus current runtime inspection plus latest checkpoint references.

This is not the source of truth. It is the stable read model for:

- status commands
- orchestrator scheduling
- operator debugging
- future dashboards or supervising agents

## Domain Model

The target model uses the following first-class concepts.

### Project

The top-level orchestration container.

A project is long-lived and may receive new work over time. It is not a static backlog snapshot.

Examples:

- `project_a`
- `agent-wave-release-train`
- `agent-wave-docs-refresh`

### InputRecord

A durable record of one external work intake event.

Supported examples in the first implementation:

- a human message such as "add feature X to project A"
- a Linear issue discovered by polling

The orchestrator should not schedule directly from raw input. It should normalize input into
`WorkItem` records and retain `InputRecord` only for traceability.

### WorkItem

The durable internal unit of work.

Examples:

- add feature A
- refactor subsystem B
- fix bug C
- update deployment workflow D

A work item is the object the orchestrator tries to drive to completion.

### Run

One execution attempt for one work item.

Examples:

- an implementation run
- a repair run
- a test run
- a review run
- an analysis run

The system should not introduce a separate first-class verification entity. Verification is simply
one or more runs whose `purpose` requests validation rather than code production.

### AgentSession

The runtime identity associated with a run.

This includes:

- provider
- model
- normalized command
- runtime session name or id
- last heartbeat and runtime metadata
- resumability metadata

`Run` and `AgentSession` are related but distinct:

- `Run` answers what execution was attempted and why
- `AgentSession` answers how and where the runtime existed

### Workspace

An execution environment for a run.

In phase 1 this is usually a local git worktree, but the model should remain generic enough that a
future runtime may use another workspace implementation.

This spec intentionally does **not** impose a hard model-level rule that only one active run may
exist on one workspace. The orchestrator may choose to run multiple runs against one workspace when
it has enough context to do so safely. The model must record enough context to make those runs
auditable.

### Checkpoint

A repository-backed continuity artifact for a meaningful run boundary.

A checkpoint always identifies:

- the work item
- the producing run
- the prior checkpoint
- the target checkpoint when the run is a validation run
- the repository path of the checkpoint file
- the commit hash that contains the checkpoint artifact

### ProjectSnapshot

The derived global view the orchestrator uses to understand:

- current progress
- active runs
- stalled runs
- latest checkpoints
- workspace health
- recommended next actions

## Verification Is a Run Purpose, Not a First-Class Entity

This is a deliberate simplification.

The system should **not** introduce a separate domain object named `VerificationTask`,
`VerificationAttempt`, or similar unless future implementation pressure genuinely requires it.

Instead:

- every execution is a `Run`
- `Run.purpose` describes what the run is for
- the orchestrator generates a run brief, usually `task.md`, that explains the specific purpose

Examples:

- a coding run has purpose `implement`
- a follow-up coding run has purpose `repair`
- a testing run has purpose `test`
- a review run has purpose `review`

The state machine should react to the structured result of a run, not to a special verification
entity.

This keeps the model smaller and matches the practical reality: "testing", "review", and "coding"
are specific run briefs, not fundamentally different scheduler primitives.

## Required Run Purposes

The first implementation should support these purposes:

- `implement`
- `repair`
- `test`
- `review`
- `analyze`

Their semantics are:

### Implement

Use when the run should advance the code or project artifact toward the work item goal.

### Repair

Use when the run should fix issues discovered by earlier runs, usually after a failed `test` or
`review`.

### Test

Use when the run should validate behavior or acceptance criteria.

### Review

Use when the run should inspect quality, correctness, design, or code health.

### Analyze

Use when the run should produce supporting information without directly moving the work item to
`done`.

## Run Brief Contract

Every launched run must receive a durable brief, usually rendered to a `task.md` file inside the
workspace or launch artifacts area.

The run brief should include at least:

- work item identity and title
- project identity
- run purpose
- current goal
- checkpoint to continue from
- current authoritative commit or workspace context
- constraints
- expected output format
- explicit next-action expectations

This brief is where the orchestrator tells the run whether it is acting as coding, testing, review,
repair, or analysis.

The scheduler must not rely on chat history to communicate this role.

## Mandatory Session Rules

### Coding and Testing Use Different Sessions

This is required.

Do not reuse a coding session as a testing session.

### Testing Always Starts a Fresh Session

This is required.

Every test run must create a fresh `AgentSession`, even when it executes immediately after a coding
run for the same work item.

### Review Also Defaults to a Fresh Session

The first implementation should treat review the same way unless there is a compelling reason not
to.

### Session Resume Is Optional

`resume_same_session` is not part of correctness.

If a coding or repair session still exists and resume is safe, the implementation may resume it.

If resume is unavailable, the next run must start a fresh session from the latest checkpoint.

## Workspace Model

### Workspace Responsibilities

A workspace is responsible for:

- providing an execution directory for a run
- isolating code changes from other work items
- preserving local progress while a run or sequence of runs is active
- serving as the place where implementation checkpoints are usually written before commit

### Workspace Kinds

The first implementation should support at least:

- `primary`
- `derived`
- `recovery`

#### Primary

The main workspace for a work item.

#### Derived

An alternate workspace created from another workspace or checkpoint when useful.

#### Recovery

A workspace rebuilt from the latest trustworthy checkpoint because an earlier workspace became
unreliable.

### Workspace Health States

At minimum:

- `healthy`
- `suspect`
- `quarantined`
- `retired`

### Workspace Rules

The model must support:

- deterministic workspace allocation per work item
- reusable workspaces across multiple runs
- path safety checks
- workspace bootstrap hooks
- before-run and after-run hooks
- before-remove cleanup hooks

The implementation should learn from Symphony here:

- keep workspace lifecycle logic in a dedicated module
- keep path validation explicit
- make hook failures and timeouts observable
- test reuse, stale-path handling, and cleanup behavior directly

## Checkpoint Model

Checkpoint design is the core of this spec.

### Why Checkpoints Exist

The checkpoint is the continuity mechanism that allows a later run to continue even if:

- the earlier session is dead
- the earlier chat history is unavailable
- the orchestrator restarted
- the earlier workspace is no longer trustworthy

### Required Checkpoint Types

The system should support exactly two checkpoint types in phase 1:

- `implementation`
- `verification`

### Implementation Checkpoint

Produced by runs with purposes such as:

- `implement`
- `repair`

Its job is to answer:

- what changed
- why it changed
- what remains
- what the next coding run should do

### Verification Checkpoint

Produced by runs with purposes such as:

- `test`
- `review`
- some `analyze` runs when they produce authoritative validation output

Its job is to answer:

- what implementation checkpoint or commit was evaluated
- what the verdict was
- what evidence supports that verdict
- what the next run should do

### Checkpoint Placement

Recommended repository layout:

`/.agvv/workitems/<work_item_id>/checkpoints/`

Recommended filenames:

- `0001-implement.md`
- `0002-review.md`
- `0003-test.md`
- `0004-repair.md`

This is only a recommendation. The important requirement is that checkpoint paths are deterministic,
machine-addressable, and durably linked to work items and runs.

### Checkpoint Commit Coupling

When a run changes product code, the implementation checkpoint must be committed together with the
code state it describes.

When a run only produces a verification artifact, the verification checkpoint may be committed alone
under `.agvv/`.

Do not split the checkpoint and the code state it describes into unrelated commits.

### Checkpoint Materialization Flexibility

The implementation may choose either of these patterns for verification runs:

1. The verification run writes its checkpoint document directly into the repository.
2. The run returns a structured result, and the orchestrator materializes the verification
   checkpoint document afterward.

Both are acceptable. The final repository state must still include:

- a checkpoint document
- a commit containing that document
- durable metadata linking the checkpoint to the run

### Required Checkpoint Content

#### Implementation Checkpoint

Must contain at least:

- work item id and title
- producing run id
- purpose
- parent checkpoint id
- current goal
- summary of changes
- files changed
- key decisions
- known issues and risks
- verification already performed
- explicit next action
- commit hash

#### Verification Checkpoint

Must contain at least:

- work item id and title
- producing run id
- purpose
- target implementation checkpoint id
- target commit hash
- verification method
- result: `pass`, `fail`, or `inconclusive`
- evidence
- explicit issues found
- explicit next action
- commit hash

### Continuity Requirement

The checkpoint chain must be sufficient for a new run to continue without:

- prior chat history
- prior terminal logs
- a still-live runtime session

Those may help, but they must not be required.

## Project Snapshot Model

`ProjectSnapshot` is a derived read model.

It should be stable enough that:

- status commands can read it directly
- the orchestrator can use it as a scheduling input
- future dashboards can render it without reimplementing scheduler logic

### ProjectSnapshot Must Include

At minimum:

- project identity and summary
- counts of work items by state
- active runs
- stalled runs
- latest checkpoint per work item
- current authoritative commit per work item
- workspace health per work item
- last significant event per work item
- recommended next action per work item

### What ProjectSnapshot Is Not

It is not:

- a repository checkpoint
- the source of truth
- a replacement for durable event records

It is a stable orchestration view.

### Symphony Lessons to Adopt

Symphony's snapshot design is worth copying in spirit:

- build a first-class snapshot API
- include running entries, retrying entries, and recent session metadata
- do not force status surfaces to reconstruct state from raw events

But unlike Symphony, `agvv` should keep durable database truth and checkpoint references.

## State Model

### WorkItem States

Required work item states:

- `queued`
- `implementing`
- `verifying`
- `blocked`
- `done`
- `canceled`

#### Meaning

- `queued`: known work, not currently being advanced
- `implementing`: the next required action is an implementation-oriented run
- `verifying`: the next required action is one or more validation runs
- `blocked`: the orchestrator cannot safely continue automatically
- `done`: required validation passed
- `canceled`: work intentionally stopped

### Run States

Required run states:

- `running`
- `succeeded`
- `failed`
- `stalled`
- `canceled`

### AgentSession States

Required session states:

- `starting`
- `running`
- `stalled`
- `finished`
- `dead`

### Workspace States

Required workspace states:

- `healthy`
- `suspect`
- `quarantined`
- `retired`

## Required Data Model

### Project

Minimum fields:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `goal TEXT`
- `state TEXT NOT NULL`
- `policy_path TEXT`
- `policy_digest TEXT`
- `policy_json TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### InputRecord

Minimum fields:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `source_type TEXT NOT NULL`
- `source_ref TEXT`
- `raw_payload_json TEXT NOT NULL`
- `normalized_work_item_id TEXT`
- `created_at TEXT NOT NULL`

Supported source types in phase 1:

- `human_message`
- `linear_issue`

### WorkItem

Minimum fields:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `title TEXT NOT NULL`
- `description TEXT`
- `kind TEXT NOT NULL`
- `priority INTEGER NOT NULL`
- `state TEXT NOT NULL`
- `acceptance_criteria_json TEXT`
- `source_type TEXT`
- `source_ref TEXT`
- `primary_workspace_id TEXT`
- `authoritative_commit TEXT`
- `latest_impl_checkpoint_id TEXT`
- `latest_verification_checkpoint_id TEXT`
- `result_summary TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Recommended kinds:

- `feature`
- `bugfix`
- `refactor`
- `ops`
- `docs`

### Run

Minimum fields:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `work_item_id TEXT NOT NULL`
- `purpose TEXT NOT NULL`
- `target_type TEXT NOT NULL`
- `target_ref TEXT`
- `workspace_id TEXT`
- `session_id TEXT`
- `state TEXT NOT NULL`
- `parent_run_id TEXT`
- `resume_from_run_id TEXT`
- `observed_start_revision TEXT`
- `observed_end_revision TEXT`
- `result TEXT`
- `result_summary TEXT`
- `failure_reason TEXT`
- `started_at TEXT`
- `finished_at TEXT`
- `last_heartbeat_at TEXT`
- `last_event_at TEXT`
- `last_event_summary TEXT`
- `runtime_meta_json TEXT`

Run target types:

- `workspace`
- `checkpoint`

### AgentSession

Minimum fields:

- `id TEXT PRIMARY KEY`
- `provider TEXT NOT NULL`
- `model TEXT`
- `command TEXT NOT NULL`
- `runtime_session_name TEXT`
- `runtime_session_id TEXT`
- `state TEXT NOT NULL`
- `resumable INTEGER NOT NULL`
- `host TEXT`
- `last_seen_at TEXT`
- `runtime_meta_json TEXT`

### Workspace

Minimum fields:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `work_item_id TEXT NOT NULL`
- `kind TEXT NOT NULL`
- `path TEXT NOT NULL`
- `branch TEXT`
- `base_commit TEXT`
- `head_commit TEXT`
- `state TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### Checkpoint

Minimum fields:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `work_item_id TEXT NOT NULL`
- `run_id TEXT NOT NULL`
- `checkpoint_type TEXT NOT NULL`
- `parent_checkpoint_id TEXT`
- `target_checkpoint_id TEXT`
- `workspace_id TEXT`
- `commit_hash TEXT NOT NULL`
- `doc_path TEXT NOT NULL`
- `summary TEXT`
- `status TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Checkpoint statuses:

- `created`
- `superseded`

### Events

The existing `task_events` table may remain physically in phase 1, but event payloads must evolve
to carry project-oriented identifiers.

Every scheduling-relevant event should include as many of these as applicable:

- `project_id`
- `work_item_id`
- `run_id`
- `workspace_id`
- `session_id`
- `checkpoint_id`

## Compatibility with Existing `agvv`

The current codebase already has:

- `tasks`
- `task_events`
- `task_reconcile_locks`
- `TaskSpec`
- `TaskSnapshot`

Phase 1 should use additive migration and semantic evolution.

### Existing Tables to Keep

- `tasks`
- `task_events`
- `task_reconcile_locks`

### New Tables to Add

- `projects`
- `input_records`
- `runs`
- `agent_sessions`
- `workspaces`
- `checkpoints`

### How `tasks` Should Evolve

The `tasks` table may remain physically named `tasks`, but it should evolve semantically into the
`WorkItem` table.

It should gain fields such as:

- `project_id`
- `title`
- `description`
- `kind`
- `priority`
- `acceptance_criteria_json`
- `primary_workspace_id`
- `authoritative_commit`
- `latest_impl_checkpoint_id`
- `latest_verification_checkpoint_id`
- `result_summary`

Do not remove old compatibility fields immediately.

### Single-Task Compatibility

The following commands must keep working:

- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

In the single-task path:

- resolve or create a project
- create one work item
- create the initial `implement` run

## Policy Contract

The orchestrator should load repository-owned policy from a checked-in contract file, preferably
`WORKFLOW.md`.

This policy should define at least:

- prompt templates
- runtime defaults
- scheduling defaults
- verification requirements
- workspace hook configuration

### Precedence

1. explicit CLI override
2. repository policy file
3. built-in defaults

### Why This Matters

This is one of the strongest Symphony ideas worth reusing:

- keep workflow policy versioned in the repository
- parse it into typed config before orchestration logic uses it
- do not let runtime code read arbitrary unvalidated front matter directly

The implementation should therefore separate:

- workflow loader
- typed config layer
- scheduler
- runtime adapter
- workspace manager
- status surface

## Scheduler Model

The scheduler operates at the project level.

It is not a single-run state machine. It is a continuous coordination loop.

### Required Main Loop

Each scheduling pass must:

1. ingest new input
2. normalize input into work items
3. reconcile active runs
4. reconcile active sessions
5. reconcile workspace health
6. refresh the project snapshot
7. decide next actions
8. launch new runs where appropriate

### Recommended Priority Order

1. handle stalled runs
2. handle suspect or quarantined workspaces
3. complete pending validation for the latest implementation checkpoints
4. launch repair runs after failed validation
5. launch new implementation runs for queued work items

### Important Scheduling Rule

The scheduler must not assume that a completed implementation run means the work item is `done`.

Only validation results can decide that.

## Lifecycle Model

Every work item follows the same closed loop:

1. intake
2. implementation run
3. implementation checkpoint
4. validation run(s)
5. verification checkpoint(s)
6. repair run if needed
7. further implementation checkpoint
8. further validation
9. done

### Intake

- create or update the project
- create an input record
- normalize the input into a work item
- set the work item state to `queued`

### Implementation

- scheduler chooses an `implement` or `repair` run
- run executes in a workspace
- run produces an implementation checkpoint
- work item transitions to `verifying`

### Validation

- scheduler launches one or more validation runs
- the run brief says whether the run is `test`, `review`, or something else
- each validation run produces a verification checkpoint

### Repair

- if validation fails, scheduler launches a `repair` run
- the `repair` run must reference the failed verification checkpoint(s)
- the run produces a new implementation checkpoint
- work item returns to `verifying`

### Completion

A work item becomes `done` only after required validation passes against an implementation
checkpoint.

Implementation completion alone is never enough.

## Recovery Model

### Run Failure

If a run returns a clear failure:

- mark the run `failed`
- store a structured reason
- update the work item state according to run purpose

Examples:

- failed implementation usually leaves the work item in `implementing`
- failed validation usually returns the work item to `implementing` for repair

### Stalled Session

If session activity stops:

- mark the run `stalled`
- update session metadata
- decide whether resume is possible

If resume is not possible, start a fresh run from the latest checkpoint.

### Workspace Failure

If a workspace becomes unreliable:

- mark it `suspect` or `quarantined`
- stop treating it as authoritative for future coding
- create a recovery workspace from the latest trustworthy checkpoint when required

### Missing Runtime History

This must not be fatal if the checkpoint chain is intact.

Correct recovery sequence:

1. load the latest checkpoint chain
2. reconstruct the intended next action
3. create a fresh run and session
4. continue from checkpoint

## Continuity Rules

These are hard requirements.

1. Every meaningful run boundary must create a repository checkpoint.
2. Every new run must be able to find the latest relevant checkpoint for its work item.
3. Every verification checkpoint must identify the implementation checkpoint or commit it evaluated.
4. The database must record the latest checkpoint references for each work item.
5. Session resume must never be required for correctness.

## Workspace Concurrency Rule

This spec does **not** impose a hard rule that only one active run may exist on one workspace.

Instead, the implementation must do the simpler and more durable thing:

- allow the model to represent multiple active runs when the orchestrator chooses to do so
- record enough context to make those runs auditable

That means at minimum:

- every run records the workspace or checkpoint it targeted
- every run records the revision it observed at start
- every validation run records exactly what commit or checkpoint it evaluated

The orchestrator is responsible for deciding whether concurrent runs on one workspace are sensible.
The persistence model must not make that decision impossible.

## Event Model

At minimum the orchestrator must emit structured events for:

- input received
- work item created
- run queued
- run started
- session started
- session resumed
- run succeeded
- run failed
- run stalled
- workspace marked suspect
- workspace quarantined
- recovery workspace created
- implementation checkpoint created
- verification checkpoint created
- validation passed
- validation failed
- work item done

These events are necessary for auditing and for reconstructing why the orchestrator made later
decisions.

## Status Surface Requirements

`agvv task status` and future project-level status commands must expose enough information to answer:

- what project this work belongs to
- what state the work item is in
- what runs are currently active
- what runs stalled most recently
- what checkpoint is currently authoritative
- what workspace is currently associated
- what the last significant event was
- what the recommended next action is

The status surface should read from `ProjectSnapshot`, not reconstruct logic ad hoc from raw tables.

## Local-First Runtime Adapter Boundary

Phase 1 must remain ACP-backed and local-first.

The implementation should preserve a clean split:

- orchestration model and scheduler are runtime-agnostic
- ACP-specific session handling stays in a runtime adapter layer
- checkpoint semantics stay independent from ACP details

Do not let ACP-specific assumptions leak into:

- work item state transitions
- checkpoint semantics
- run continuity rules

## Symphony Lessons Worth Reusing

The `symphony` reference implementation is not the target architecture, but several design lessons
are worth borrowing.

### 1. Strong Layering

Adopt a clean split between:

- policy loading
- typed config
- scheduler
- runtime adapter
- workspace manager
- status surface

Do not let those concerns collapse into one module.

### 2. Typed Policy Access

Do not let scheduler code read raw `WORKFLOW.md` front matter directly.

Normalize and validate workflow policy first, then expose typed values.

### 3. Dedicated Workspace Lifecycle Logic

Treat workspace lifecycle as a first-class module with:

- deterministic paths
- bootstrap hooks
- cleanup hooks
- path safety checks
- direct tests

### 4. First-Class Snapshot Surface

Make snapshot generation a real API, not an incidental status helper.

### 5. Cleanup Hooks Can Manage More Than Directories

Workspace cleanup hooks may also clean associated resources such as PRs or branch references when
the repository workflow requires that behavior.

## Symphony Lessons Not To Copy

The following Symphony choices should **not** be copied directly into `agvv`:

### 1. No Durable Database

`agvv` should keep SQLite as durable scheduler truth.

### 2. Tracker-Only Continuity

`agvv` should use checkpoint-first continuity, not issue-state-plus-workspace-only continuity.

### 3. No Explicit Checkpoint Chain

`agvv` must keep explicit checkpoint objects and references.

## Implementation Boundaries in the Current Codebase

The primary modification surfaces are:

- [`agvv/runtime/models.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/runtime/models.py)
- [`agvv/runtime/store.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/runtime/store.py)
- [`agvv/runtime/core.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/runtime/core.py)
- [`agvv/runtime/session_lifecycle.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/runtime/session_lifecycle.py)
- [`agvv/runtime/dispatcher.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/runtime/dispatcher.py)
- [`agvv/orchestration/layout.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/orchestration/layout.py)
- [`agvv/orchestration/acp_ops.py`](/home/yunda/projects/agent-wave/worktrees/chore-checkpoint-first-spec-v3/agvv/orchestration/acp_ops.py)

Additional modules will likely be needed for:

- project policy loading
- run brief rendering
- checkpoint materialization
- project snapshot projection
- scheduler logic beyond the current task-only dispatcher

## Recommended Implementation Order

Keep the repository working after each phase.

### Phase 1: Domain and Schema Primitives

- add `Project`, `InputRecord`, `Run`, `AgentSession`, `Workspace`, and `Checkpoint`
- evolve `tasks` semantically into `WorkItem`
- preserve compatibility paths for existing CLI behavior

### Phase 2: Checkpoint Materialization

- define repository checkpoint paths
- define checkpoint templates
- implement implementation checkpoint writing
- implement verification checkpoint writing
- persist checkpoint metadata in SQLite

### Phase 3: Session and Run Lifecycle Refactor

- separate run identity from session identity
- make test runs always use fresh sessions
- make fresh-run-from-checkpoint the default fallback
- keep session resume optional

### Phase 4: Project Snapshot and Scheduler

- add project snapshot projection
- upgrade daemon reconciliation to project-level logic
- schedule implementation, validation, and repair loops

### Phase 5: CLI and Docs Alignment

- update status output to use project snapshots
- update operator-facing docs
- preserve single-task workflow

## Testing Requirements

### Schema and Model Tests

- project, work item, run, workspace, session, and checkpoint serialization
- compatibility reads for legacy task rows
- policy loading and validation

### Checkpoint Tests

- checkpoint path generation
- checkpoint file rendering
- checkpoint commit linkage
- checkpoint chain reconstruction
- fresh-run continuation from checkpoint alone

### Session Tests

- coding session launch
- testing always uses a fresh session
- stalled session detection
- optional session resume
- fresh-session fallback from checkpoint

### Workspace Tests

- deterministic workspace path allocation
- workspace reuse
- stale path handling
- path safety and symlink protection
- recovery workspace creation from checkpoint
- hook failure and timeout handling

### Scheduler Tests

- queued work starts implementation
- implementation checkpoint moves work into validation
- failed validation triggers repair
- successful validation marks work item done
- project snapshot reflects active and stalled runs

### CLI Tests

- legacy `task run/status/retry/cleanup` still work
- status output includes checkpoint and project-level information
- retry from checkpoint works when prior session is unavailable

## Acceptance Criteria

This design is implemented only when all of the following are true:

1. A single-task `agvv task run` still works.
2. The system can represent multiple work items in one project.
3. The system can represent multiple runs for one work item.
4. Coding and testing are stored as different sessions.
5. Testing always starts a fresh session.
6. Every meaningful run produces a repository checkpoint and corresponding metadata row.
7. A new run can continue from the latest checkpoint without prior chat history.
8. Validation success, not implementation completion, controls whether a work item becomes `done`.
9. The project snapshot can explain current progress and next actions without replaying raw
   transcripts.
10. The runtime adapter remains local-first and ACP-backed in phase 1 without leaking ACP-specific
    assumptions into the checkpoint model.

## Coding-Agent Implementation Guidance

When implementing this spec:

- prefer additive migrations over destructive renames
- keep old command behavior working while changing internal semantics
- keep checkpoint templates explicit and machine-addressable
- treat repository checkpoints as first-class continuity artifacts
- persist all scheduling-relevant decisions in SQLite
- do not encode correctness only in prompt text
- assume the next run may start with zero chat history

If a design choice is ambiguous, prefer the design that makes checkpoint-based recovery and project
level reasoning easier to implement and audit.
