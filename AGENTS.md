# Repository Guidelines

## Project Structure & Module Organization
Core Python code is in `src/agvv`.
- `src/agvv/cli`: Typer CLI commands (`project`, `task`, `run`, `session`, `checkpoint`, `daemon`).
- `src/agvv/core`: orchestration logic (task lifecycle, runs, checkpoints, sessions).
- `src/agvv/daemon`: background monitoring and reconciliation.
- `src/agvv/utils`: Git, Markdown, and formatting helpers.

Tests live in `tests/` and use realistic temp repos and Git operations. User-facing docs are in `docs/` (`overview.md`, `workflow.md`, `cli.md`, `architecture.md`).

## Build, Test, and Development Commands
- `pip install -e .` (or `uv pip install -e .`): editable install.
- `agvv --help`: verify CLI entrypoint and command surface.
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -v`: run full suite.
- `AGVV_RUN_REAL_AGENT_E2E=1 PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_real_agent_e2e`: run real `acpx -> codex` E2E.
- `python3 -m py_compile src/agvv/core/*.py src/agvv/daemon/*.py`: quick syntax check.

## Coding Style & Naming Conventions
Target Python 3.10+ with 4-space indentation and type hints where useful. Prefer small deterministic functions and explicit state transitions. Use `snake_case` for modules/functions/files. Task names exposed to users should be machine-friendly (for example `fix-login-bug`). Keep comments minimal and focused on non-obvious behavior.

## Testing Guidelines
Testing framework: standard-library `unittest`. Name files `test_*.py` and methods `test_*`. Favor fault-oriented, end-to-end style tests over heavy mocking. When changing run/daemon/checkpoint/merge behavior, add or update regression coverage in `tests/test_robustness.py` or `tests/test_run.py`.

## Commit & Pull Request Guidelines
Use concise imperative commit subjects, optionally with prefixes (for example `feat:`, `fix:`, `docs:`). Keep each commit scoped to one logical change. PRs should include purpose, behavior changes, verification commands run, and any CLI/doc updates. Link relevant issues when available.

## Architecture Notes
Keep agvv small and file-backed. Do not add databases or heavy orchestration layers. Checkpoints remain Git-based, and daemon decisions must rely on observable runtime facts.
