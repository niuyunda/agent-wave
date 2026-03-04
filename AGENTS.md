# AGENTS.md

## Cursor Cloud specific instructions

**Agent Wave (`agvv`)** is a Python CLI tool for orchestrating parallel coding tasks by AI agents using Git worktrees, tmux, and SQLite.

### Development commands

Standard commands are in `pyproject.toml` and `README.md`. Quick reference:

- **Install deps:** `uv sync --dev`
- **Lint:** `uv run ruff check .`
- **Test:** `uv run pytest` (101 tests, ~2s; all mock external deps—no tmux/gh needed)
- **Test with coverage:** `uv run pytest --cov=agvv`
- **Run CLI:** `uv run agvv --help`

### Non-obvious notes

- `uv` must be on `PATH`. If not found, install via `curl -LsSf https://astral.sh/uv/install.sh | sh` and add `$HOME/.local/bin` to `PATH`.
- The test suite mocks `git`, `tmux`, and `gh` — no external services or authentication are needed to run tests.
- For real end-to-end usage (not tests), `tmux` and `gh` (authenticated) must be available on the system.
- The CLI entry point is `agvv` (mapped to `agvv.cli:app` in `pyproject.toml`). From a source checkout, use `uv run agvv ...` instead of `agvv ...`.
- SQLite DB path defaults to `./tasks.db` or can be set via `AGVV_DB_PATH` env var.
