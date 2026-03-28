# Checkpoint-First Multi-Agent Orchestration Spec

## Purpose

This document is the implementation specification for coding agents modifying `agent-wave` (`agvv`).

It replaces the earlier task/session-centric design with a checkpoint-first orchestration model that is meant to be implemented directly from this file, without relying on prior chat context.

This spec is written for coding agents. It is deliberately operational. It defines:

- the required domain model
- the required storage model
- the required lifecycle rules
- the required checkpoint rules
- the required recovery behavior
- the required compatibility constraints for the existing `agvv` CLI and runtime

## Executive Summary

`agvv` must evolve from a single-task runner into a project-oriented orchestrator.

The new system must:

- ingest work from different sources such as human messages or Linear issues
- normalize that work into durable internal work items
- run multiple work items in parallel
- allow multiple runs to exist for the same work item over time
- treat coding and testing as different sessions
- treat testing as a fresh session every time
- preserve isolated local workspaces for code execution in the first implementation
- create repository checkpoints that allow later runs to continue without prior chat history
- recover from stalled or dead sessions without losing continuity
- expose a project-level operator snapshot for status and scheduling

The central design decision is:

**Correctness must depend on repository checkpoints plus durable runtime metadata, not on keeping the same runtime session alive.**

Resuming the same session is allowed only as an optimization. It must never be a correctness dependency.

## What This Spec Optimizes For

Every design choice in this document should improve at least one of:

- isolation
- recoverability
- observability
- auditability
- implementation clarity
- compatibility with the existing local-first `agvv` runtime

## Non-Goals

The first implementation must not attempt:

- arbitrary DAG orchestration across external systems
- autonomous merge conflict resolution
- automatic destructive recovery after ambiguous git state
- provider-specific prompt optimization beyond role templates and project policy
- replacing ACP in phase 1
- building a cloud-native execution fabric before the local-first model is stable

## First-Principles Problem Statement

The current system assumes:

- one task
- one worktree
- one coding session
- one terminal outcome

That model is too small for real orchestration.

In real use:

- a project may contain multiple work items
- new work items may arrive over time
- each work item may require multiple coding and verification cycles
- any session may stall or die
- verification must influence what happens next
- the orchestrator must retain enough context to continue even when the previous run is gone

From first principles, the orchestrator must always be able to answer these questions durably:

1. What work exists for this project?
2. What has been tried for each work item?
3. What code state is currently authoritative for each work item?
4. What repository checkpoint allows a new run to continue if the current run disappears?
5. What is the overall project status and recommended next action?

If the system cannot answer those questions from durable state plus repository contents, it is not yet a reliable orchestrator.

## Core Design Thesis

The system is **project-driven**, **checkpoint-first**, and **run-aware**.

That means:

- `Project` is the scheduling scope
- `WorkItem` is the durable unit of work
- `Run` is one execution attempt against a work item
- `Workspace` is an execution environment, usually a git worktree in phase 1
- `Checkpoint` is the handoff contract between runs
- `ProjectSnapshot` is the orchestrator's derived global view

The most important correctness rule is:

**A later run must be able to continue from the latest repository checkpoint even if it has no access to earlier chat history or runtime state.**

## Terminology and Required Mappings

This spec uses new domain terms. The implementation must still preserve compatibility with the current code and CLI.

### Project

Top-level orchestration container.

Examples:

- `project_a`
- `agent-wave-docs-refresh`

A project is not a fixed backlog snapshot. New work items may be added over time.

### WorkItem

Durable internal unit of work.

Examples:

- add feature A
- add feature B
- refactor subsystem C
- fix bug D

A work item is the durable business object that the orchestrator tries to move to `done`.

### Run

One execution attempt by one agent role for one work item.

Examples:

- implement run
- repair run
- review run
- test run
- analyze run

`Run` is the execution unit. It is not the same thing as a session.

### AgentSession

The runtime identity used by a run.

In the first implementation this is ACP-backed and local-first.

An agent session captures:

- provider
- model
- normalized command
- runtime session name or id
- last heartbeat
- runtime status
- resumability metadata

### Workspace

Execution environment for a run.

In phase 1 this is usually a git worktree. The model should still remain generic enough that a future runtime can provide another workspace implementation.

### Checkpoint

Repository-backed handoff artifact for a completed or meaningful run boundary.

A checkpoint always has:

- a repository path
- a commit hash
- a checkpoint type
- a producing run
- a work item
- a summary of the state at that point

The checkpoint is not optional metadata. It is the continuity mechanism.

### ProjectSnapshot

Derived read model used by the orchestrator and status surfaces.

This is not the source of truth. Durable tables plus repository checkpoints remain authoritative.

### Legacy Compatibility Mapping

The current codebase already has a `tasks` table and `TaskSpec`/`TaskSnapshot` models.

For phase 1 migration:

- the existing `tasks` table may remain physically named `tasks`
- each `tasks` row should evolve semantically into a `WorkItem`
- the existing `task_events` table may remain as the event log table
- the existing `task run/status/retry/cleanup` CLI must continue to work
- single-task commands should implicitly create or attach a `Project` and one `WorkItem`

The implementation should use the clearer domain language internally even if table names remain temporarily compatible.

## Repository-Owned Policy Contract

The system should load a repository-owned policy file, preferably `WORKFLOW.md`, to define:

- prompt templates by run purpose
- scheduling defaults
- verification requirements
- runtime defaults
- workspace bootstrap rules

Minimum precedence order:

1. explicit CLI override
2. repository policy file
3. built-in defaults

The resolved policy used for a project must be stored durably on the project row by path, digest, and resolved spec JSON.

## Source of Truth and Continuity Model

The system has two different durable layers and both are required.

### Layer 1: Runtime Truth

Stored in SQLite.

This captures:

- projects
- work items
- runs
- sessions
- workspaces
- checkpoint metadata
- events

This layer is used for scheduling, status, and recovery planning.

### Layer 2: Repository Continuity

Stored in the repository as checkpoint documents and corresponding commits.

This captures:

- what a run accomplished
- what code state it operated on
- what remains to be done
- what the next run should do

This layer is used for handoff and continuity when a new run starts without prior chat history.

### Required Rule

Runtime truth and repository continuity must point at each other:

- the database must reference the latest checkpoint id and commit hash
- each checkpoint document must identify the producing run and prior checkpoint

Neither layer is sufficient alone.

## Required Domain Model

### 1. Project

Project fields should include at least:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `goal TEXT`
- `state TEXT NOT NULL`
- `policy_path TEXT`
- `policy_digest TEXT`
- `policy_json TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Project states:

- `active`
- `blocked`
- `completed`
- `canceled`

### 2. InputRecord

Input record fields should include at least:

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

### 3. WorkItem

Work item fields should include at least:

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

Work item states:

- `queued`
- `implementing`
- `verifying`
- `blocked`
- `done`
- `canceled`

### 4. Run

Run fields should include at least:

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

Run purposes in phase 1:

- `implement`
- `repair`
- `review`
- `test`
- `analyze`

Run target types in phase 1:

- `workspace`
- `checkpoint`

Run states:

- `running`
- `succeeded`
- `failed`
- `stalled`
- `canceled`

### 5. AgentSession

Agent session fields should include at least:

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

Session states:

- `starting`
- `running`
- `stalled`
- `finished`
- `dead`

### 6. Workspace

Workspace fields should include at least:

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

Workspace kinds in phase 1:

- `primary`
- `derived`
- `recovery`

Workspace states:

- `healthy`
- `suspect`
- `quarantined`
- `retired`

### 7. Checkpoint

Checkpoint fields should include at least:

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

Checkpoint types:

- `implementation`
- `verification`

Checkpoint status values:

- `created`
- `superseded`

### 8. Event Log

The existing `task_events` table may remain in phase 1, but it must evolve to carry project/work item/run/checkpoint identifiers.

Required event payload identity:

- `project_id`
- `work_item_id`
- `run_id`
- `workspace_id`
- `session_id`
- `checkpoint_id`

### 9. ProjectSnapshot

This may be stored as a cached projection or rebuilt on demand.

At minimum it must expose:

- project summary
- work item counts by state
- active runs
- stalled runs
- latest checkpoint per work item
- workspace health summary
- recommended next actions

## Run Purpose Rules

### Implement Run

Purpose:

- create or advance code for a work item

Requirements:

- may modify product code
- must produce an implementation checkpoint when a meaningful handoff state is reached

### Repair Run

Purpose:

- modify code after a failed review or test

Requirements:

- same as implement run
- must cite the verification checkpoints it is addressing

### Review Run

Purpose:

- inspect the current implementation from a review perspective

Requirements:

- must use a fresh session
- must produce a verification checkpoint
- must not be treated as completion by itself

### Test Run

Purpose:

- validate behavior or other acceptance criteria

Requirements:

- must always use a fresh session
- must produce a verification checkpoint
- must record exactly what commit or checkpoint was tested

### Analyze Run

Purpose:

- perform supporting analysis without directly changing completion state

Requirements:

- may create a verification checkpoint when its output is part of the durable decision trail

## Mandatory Session Rules

### Coding and Testing Use Different Sessions

This is required.

Do not reuse a coding session as a testing session.

### Testing Always Starts a New Session

This is required.

Every test run must create a new `AgentSession`, even when it is testing the same work item immediately after coding.

### Review Also Defaults to a New Session

Review should also use a new session in phase 1.

### `resume_same_session` Is Optional

Session resume is not part of correctness.

The system may resume a coding or repair session when:

- the runtime still exists
- the session is known resumable
- the workspace is still suitable

But if resume is not possible, the next run must continue from the latest checkpoint with a fresh session.

## Workspace Rules

This spec intentionally does **not** impose a hard global rule that only one active run may exist on a workspace.

The model must allow multiple active runs to exist concurrently when the orchestrator chooses to do so.

What the implementation must do is record enough context to avoid ambiguity:

- every run must record the target workspace or target checkpoint it started from
- every run must record the revision it observed when it started
- every run that matters for verification must record the exact revision or checkpoint it evaluated

The orchestrator remains responsible for deciding whether concurrent runs on the same workspace are sensible.

### Primary Workspace

Each work item should normally have one primary workspace that represents the main local code line for that work item.

### Derived or Recovery Workspaces

The system may create additional workspaces when useful:

- to replay from a checkpoint
- to isolate recovery from a suspect workspace
- to run an alternate attempt

### Workspace Recovery Rule

If a workspace becomes unreliable, recovery must start from the latest trustworthy checkpoint, not from chat history.

## Checkpoint Rules

Checkpoint design is the core of this spec.

### Rule 1: Every Meaningful Run Boundary Produces a Repository Checkpoint

If a run completes a meaningful step, its result must be materialized as a checkpoint in the repository and committed.

### Rule 2: Two Checkpoint Types Must Exist

#### Implementation Checkpoint

Produced by:

- implement runs
- repair runs

Purpose:

- capture code progress
- capture decisions
- tell the next coding run what to do next

#### Verification Checkpoint

Produced by:

- review runs
- test runs
- other authoritative validation runs

Purpose:

- capture what implementation checkpoint or commit was evaluated
- capture pass/fail/inconclusive status
- capture evidence and next action

### Rule 3: Checkpoints Must Live in the Repository

Recommended repository layout:

`/.agvv/workitems/<work_item_id>/checkpoints/`

Recommended file naming:

- `0001-implement.md`
- `0002-review.md`
- `0003-test.md`
- `0004-repair.md`

### Rule 4: Checkpoint and Commit Must Stay Coupled

When product code changes are part of the run output, the implementation checkpoint must be committed together with the code changes it describes.

When verification output is the only repository change, the verification checkpoint commit may contain only files under `.agvv/`.

Do not split checkpoint content and the code state it describes into unrelated commits.

### Rule 5: A New Run Must Be Able to Continue from Checkpoint Alone

The next run must not require:

- previous chat history
- previous terminal logs
- the previous session still being alive

Those may help, but the checkpoint chain must be sufficient.

### Rule 6: Verification Checkpoints Must Cite Their Target

A verification checkpoint must record:

- target implementation checkpoint id
- target commit hash
- run purpose
- result
- evidence
- next action

### Rule 7: Materialization Flexibility Is Allowed

For implementation runs, the agent will usually write checkpoint content directly in its execution workspace.

For verification runs, the implementation may either:

- let the verification run write the checkpoint file itself, or
- let the orchestrator materialize the verification checkpoint from the run's structured result

Both are acceptable as long as the end result is the same:

- a repository checkpoint file exists
- it is committed
- it is linked to the producing run

## Required Checkpoint Content

### Implementation Checkpoint Template

Every implementation checkpoint must contain at least:

- work item id and title
- producing run id
- parent checkpoint id
- current goal
- what changed
- files changed
- key decisions
- known risks or unfinished items
- verification already performed
- explicit next action
- commit hash

### Verification Checkpoint Template

Every verification checkpoint must contain at least:

- work item id and title
- producing run id
- target implementation checkpoint id
- target commit hash
- verification method
- result: `pass`, `fail`, or `inconclusive`
- evidence
- concrete issues found
- explicit next action
- commit hash

These templates must be stable and machine-addressable so that a new run can load them predictably.

## Lifecycle Model

Every work item follows the same closed loop:

1. intake and normalization
2. implementation
3. implementation checkpoint
4. verification
5. verification checkpoint
6. repair if needed
7. further implementation checkpoint
8. further verification
9. done

### Intake

- create or update the project
- create an input record
- normalize input into a work item
- queue the work item

### Implementation Phase

- orchestrator starts an implement run
- the run may create or reuse a workspace
- the run changes code
- the run produces an implementation checkpoint

### Verification Phase

- orchestrator starts review and/or test runs according to policy
- each verification run uses a fresh session
- each verification run produces a verification checkpoint

### Repair Phase

- if verification fails, the orchestrator starts a repair run
- the repair run must reference the failed verification checkpoints
- the repair run produces a new implementation checkpoint

### Completion

A work item becomes `done` only after required verification succeeds against an implementation checkpoint.

Implementation success alone is never enough.

## WorkItem State Machine

Required transitions:

- `queued -> implementing`
- `implementing -> verifying`
- `verifying -> done`
- `verifying -> implementing` when repair is needed
- `implementing -> blocked` on unrecoverable runtime or workspace issues
- `verifying -> blocked` on unrecoverable verification or recovery issues
- any active state -> `canceled`

Rules:

- `implementing` means the next required action is an implement or repair run
- `verifying` means the next required action is one or more verification runs
- `blocked` means the orchestrator cannot safely continue automatically

## ProjectSnapshot Requirements

`ProjectSnapshot` must be a stable derived read model used by:

- `agvv ... status`
- future dashboards
- supervising agents
- scheduling logic

At minimum it must expose:

- project id and summary
- work item counts by state
- all active runs
- all stalled runs
- latest checkpoint per work item
- current authoritative commit per work item
- workspace health summary
- last significant event per work item
- recommended next action per work item

`ProjectSnapshot` is not a repository checkpoint.

It is an orchestration view built from:

- durable database rows
- current runtime inspection
- latest checkpoint references

## Scheduler Requirements

The scheduler operates at the project level, not the single-run level.

Each scheduling pass must:

1. ingest new inputs
2. normalize them into work items
3. reconcile active runs and sessions
4. refresh workspace status
5. refresh the project snapshot
6. select next actions
7. launch new runs where appropriate

Recommended priority order:

1. handle stalled runs and suspect workspaces
2. finish pending verification for existing implementation checkpoints
3. launch repair runs for failed verification
4. launch new implementation runs for queued work items

The scheduler must not assume that one finished run means the work item is done.

## Failure and Recovery Rules

### Run Failure

If a run returns a clear failure:

- mark the run `failed`
- record a structured failure reason
- update the work item state according to run purpose

Examples:

- implement failed: work item usually remains `implementing`
- review/test failed: work item returns to `implementing` for repair

### Stalled Session

If a session stops making progress:

- mark the run `stalled`
- update the session state
- decide whether to resume or replace the session

If resume is impossible, start a fresh run from the latest checkpoint.

### Workspace Failure

If the workspace is unreliable:

- mark it `suspect` or `quarantined`
- stop treating it as trustworthy for the next coding step
- create a recovery workspace from the latest trustworthy checkpoint when needed

### Missing Runtime History

This is not fatal if the checkpoint chain is intact.

The correct recovery path is:

1. load latest checkpoint chain for the work item
2. reconstruct intended next action
3. create a fresh session and run
4. continue from checkpoint

## Local-First ACP Runtime Requirement

Phase 1 must remain ACP-backed and local-first.

The implementation must still preserve a clean boundary so that a future runtime adapter can replace ACP without rewriting the orchestration model.

Required split:

- orchestration model and scheduler are runtime-agnostic
- ACP-specific session management remains in a runtime adapter layer
- checkpoint creation rules are independent from ACP details

Do not let ACP-specific assumptions leak into checkpoint semantics or work item state transitions.

## Required Storage Plan

The first implementation should use additive migration and compatibility-first schema changes.

### Existing Tables to Keep

- `tasks`
- `task_events`
- `task_reconcile_locks`

### Required New Tables

- `projects`
- `input_records`
- `runs`
- `agent_sessions`
- `workspaces`
- `checkpoints`

### Required Evolution of `tasks`

The existing `tasks` table should evolve semantically into work items and gain fields such as:

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

## CLI Compatibility Requirements

The following commands must continue to work:

- `agvv task run`
- `agvv task status`
- `agvv task retry`
- `agvv task cleanup`
- `agvv daemon run`

### `task run`

In the single-task path:

- create or resolve a project
- create one work item
- create the initial implement run

### `task status`

Must expose enough project/work item/run/checkpoint data to explain:

- current work item state
- active runs
- latest checkpoints
- current authoritative commit
- workspace status
- recommended next action

### `task retry`

Must no longer be modeled as "rerun the same task session".

It must decide whether to:

- resume a resumable coding session, or
- start a fresh run from the latest checkpoint

### Future Commands

The architecture must not block later addition of:

- `agvv project run`
- `agvv project status`
- `agvv project cleanup`

## Required Event Types

At minimum the system must emit structured events for:

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
- verification passed
- verification failed
- work item done

Each event must include stable identifiers for the relevant project, work item, run, workspace, session, and checkpoint.

## Implementation Boundaries in the Current Codebase

Coding agents implementing this spec should treat these areas as the primary modification surfaces:

- [`agvv/runtime/models.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/runtime/models.py)
- [`agvv/runtime/store.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/runtime/store.py)
- [`agvv/runtime/core.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/runtime/core.py)
- [`agvv/runtime/session_lifecycle.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/runtime/session_lifecycle.py)
- [`agvv/runtime/dispatcher.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/runtime/dispatcher.py)
- [`agvv/orchestration/layout.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/orchestration/layout.py)
- [`agvv/orchestration/acp_ops.py`](/home/yunda/projects/agent-wave/worktrees/chore-multi-agent-orchestration-spec-rewrite/agvv/orchestration/acp_ops.py)

Additional modules will likely be needed for:

- project snapshot projection
- checkpoint materialization
- project policy loading
- scheduler logic beyond the current task-only dispatcher

## Recommended Implementation Order

Keep the repository working after each step.

### Phase 1: Schema and Domain Primitives

- add project/run/workspace/session/checkpoint primitives
- evolve `tasks` into work items semantically
- preserve compatibility shims

### Phase 2: Checkpoint Materialization

- create repository checkpoint paths and templates
- implement implementation checkpoint writing
- implement verification checkpoint writing
- link checkpoints durably in SQLite

### Phase 3: Run- and Session-Aware Lifecycle

- separate run identity from session identity
- ensure testing always creates a fresh session
- ensure fresh-run-from-checkpoint is the default recovery path

### Phase 4: Project Snapshot and Scheduler

- add project-level snapshot projection
- upgrade daemon reconciliation to project-level scheduling
- schedule implementation, verification, and repair loops

### Phase 5: CLI and Docs Alignment

- update CLI status surfaces
- update README and operator-facing documentation
- preserve single-task UX

## Testing Requirements

### Schema and Model Tests

- project/work item/run/workspace/checkpoint serialization
- compatibility reads for legacy task rows
- policy loading and validation

### Checkpoint Tests

- implementation checkpoint path generation
- verification checkpoint path generation
- checkpoint commit linkage
- checkpoint chain reconstruction
- fresh-run continuation from checkpoint without previous session

### Session and Runtime Tests

- coding session launch
- test session always new
- stalled session detection
- resume optionality for coding runs
- fresh session fallback from checkpoint

### Workspace Tests

- primary workspace creation
- recovery workspace creation from checkpoint
- quarantined workspace handling

### Scheduler Tests

- queued work item starts implementation
- implementation checkpoint triggers verification
- verification failure triggers repair
- successful verification marks work item done
- project snapshot reflects active and stalled runs correctly

### CLI Tests

- legacy `task run/status/retry/cleanup` still work
- status output includes checkpoint and project-level information
- retry from checkpoint works when prior session is unavailable

## Acceptance Criteria

This spec is implemented only when all of the following are true:

1. A single-task `agvv task run` still works.
2. The system can represent multiple work items in one project.
3. The system can represent multiple runs for one work item.
4. Coding and testing are persisted as different sessions.
5. Testing always starts a new session.
6. Every meaningful run produces a repository checkpoint and corresponding metadata row.
7. A new run can continue from the latest checkpoint without access to prior chat history.
8. Verification success, not coding completion, controls whether a work item becomes `done`.
9. The project snapshot can explain current progress and next actions without scanning raw transcripts.
10. The local-first ACP implementation works while keeping runtime adapter boundaries clean.

## Coding-Agent Implementation Guidance

When implementing this spec:

- prefer additive migrations over destructive renames
- preserve old command behavior while changing the internal model
- keep checkpoint templates explicit and machine-addressable
- never encode correctness assumptions only in prompt text
- persist all scheduling-relevant decisions in SQLite
- treat repository checkpoints as first-class continuity artifacts
- treat session resume as optional
- assume the next run may start with zero chat history

If you need to choose between a design that is elegant in runtime code and a design that makes checkpoint-based recovery explicit, prefer the recovery-explicit design.
