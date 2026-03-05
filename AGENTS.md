# `agvv` Codebase Guide for AI Agents

Welcome! You are an AI Agent tasked with working on the `agvv` (Agent Wave) codebase. 
This document provides a concise overview of the project architecture and boundaries to help you safely navigate and modify the code.

## Core Philosophy (The "Why")
`agvv` orchestrates parallel coding tasks in isolated environments.
It uses **git worktrees** to ensure absolute file-system isolation (so you don't pollute the user's main branch) and **tmux** to ensure background process isolation (so you can run concurrently without blocking the user's terminal).

## Architecture & Directory Structure
The architecture is strictly divided into two layers:

### 1. `agvv/orchestration/` (The "Doer")
- **Responsibility**: System side-effects. This layer interacts with the OS, `git`, and `tmux`.
- **Key Constraint**: It must remain **stateless**. It knows nothing about databases or task lifecycles.
- **Files**:
  - `layout.py`: Manages the physical directory layout (e.g., bare repo `repo.git`, `main` worktree, and `feature` worktrees).
  - `executor.py`, `git_ops.py`, `tmux_ops.py`: Wrappers around subprocess calls.

### 2. `agvv/runtime/` (The "Brain")
- **Responsibility**: State-machine logic and persistence.
- **Key Constraint**: It relies on SQLite (`store.py`) for lock-safe concurrency and state persistence.
- **Files**:
  - `models.py`: Pydantic definitions (e.g., `TaskState`, `TaskSpec`).
  - `store.py`: SQLite persistence layer.
  - `core.py`: The main business logic connecting CLI intents to state changes.
  - `dispatcher.py`: The daemon that periodically reconciles tmux session status with the database.

### 3. `agvv/cli.py` (The "Face")
- **Responsibility**: The user interface. Uses `typer` to parse commands and route them to `runtime/core.py` and `runtime/dispatcher.py`.

## Rules for Agents Modifying This Codebase

1. **Occam's Razor**: Do not introduce unnecessary abstractions or third-party dependencies. The project should remain lightweight.
2. **First Principles**: Always question if a new feature solves the fundamental problem of "environment and process isolation." 

Read these instructions carefully before making any codebase modifications.
