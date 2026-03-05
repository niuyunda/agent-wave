# CI/CD Pipeline

## Overview

The project uses GitHub Actions for automated CI/CD, consisting of two independent pipelines:

| Pipeline | File | Trigger | Purpose |
|----------|------|---------|---------|
| CI | `.github/workflows/ci.yml` | push / PR | Quality gate: lint, format, docs, tests, build |
| Publish | `.github/workflows/publish.yml` | git tag `v*` | Release package to PyPI |

---

## CI Pipeline

### Triggers

```text
push to: main, feat-*, fix-*, refactor-*, codex/*
any Pull Request
manual trigger (workflow_dispatch)
```

### Execution Flow

```text
┌─────────────────────────────────────────────────────────┐
│  lint job                    test job (matrix)          │
│  ─────────────────           ──────────────────────     │
│  ruff check .                Python 3.10                │
│  ruff format --check .       Python 3.12                │
│  interrogate --fail-under=100│  pytest --cov=agvv       │
└──────────────┬───────────────┴──────────────┬──────────┘
               │          both pass           │
               └──────────────┬───────────────┘
                              ▼
                        build job
                        ─────────
                        uv build
                        upload dist/ artifact
```

### Job Details

#### `lint` — Code Quality

Runs on Python 3.12. All three checks must pass:

| Command | What it checks |
|---------|---------------|
| `uv run ruff check .` | Code style and errors (linting) |
| `uv run ruff format --check .` | Code formatting (check only, no auto-fix) |
| `uv run interrogate agvv --fail-under=100 --quiet` | Docstring coverage must be 100% |

> **Why enforce docstrings in CI?**
> The project has a `.githooks/pre-commit` hook for local enforcement, but git hooks are opt-in. Enforcing this in CI guarantees every commit merged to `main` meets the requirement.

#### `test` — Multi-version Matrix

Runs the full test suite on **Python 3.10 and 3.12**:

```text
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing --cov-report=xml
```

- Coverage report (`coverage.xml`) is uploaded as an artifact only from the Python 3.12 run
- The project declares `requires-python = ">=3.10"`; matrix testing verifies the minimum supported version

#### `build` — Build Verification

Runs only after both `lint` and `test` pass:

```text
uv build
```

The resulting wheel and sdist are uploaded as a `dist` artifact for debugging or manual download.

### Concurrency Control

A new push to the same branch or PR automatically cancels any in-progress CI run:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

---

## Publish Pipeline

### Triggers

```text
push a git tag matching v* (e.g. v0.1.2, v1.0.0)
manual trigger (workflow_dispatch) — runs verify only, does not publish
```

### Execution Flow

```text
verify job
─────────────────────────────────
ruff check .
ruff format --check .
interrogate --fail-under=100 --quiet
pytest
         │
         │ passes
         ▼
publish job (tag trigger only)
─────────────────────────────────
verify pyproject.toml version == git tag version
uv build
pypa/gh-action-pypi-publish (OIDC)
         │
         ▼
PyPI: agent-wave==x.y.z
```

### Job Details

#### `verify` — Pre-release Quality Gate

Runs the same lint and test checks as the CI pipeline. Even if CI already passed on the same commit, the publish pipeline re-verifies before releasing.

#### `publish` — Release to PyPI

**Condition**: `if: startsWith(github.ref, 'refs/tags/')` — only executes on tag pushes; manual dispatch skips this job.

**Version consistency check**:

Before building, the workflow verifies that the `version` field in `pyproject.toml` matches the git tag:

```bash
TAG="${GITHUB_REF#refs/tags/v}"          # e.g. 0.1.2
PKG_VER=$(grep '^version = ' pyproject.toml | ...)
[ "$TAG" != "$PKG_VER" ] && exit 1       # abort if mismatch
```

**PyPI authentication**: Uses [OIDC Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no PyPI token stored as a secret. Authorization is delegated through the `pypi` GitHub environment.

**Least-privilege permissions**: `id-token: write` is declared only at the `publish` job level. The `verify` job has read-only permissions.

---

## Release SOP

Complete steps to publish a new version to PyPI:

### Step 1 — Verify `main` is clean

```bash
git checkout main
git pull origin main
# Confirm CI is green on main in GitHub Actions
```

### Step 2 — Bump the version

Edit `pyproject.toml`:

```toml
[project]
version = "0.1.2"   # was 0.1.1
```

Follow [Semantic Versioning (SemVer)](https://semver.org/):

| Type | Example | When to use |
|------|---------|-------------|
| Patch | `0.1.1 → 0.1.2` | Bug fixes, documentation updates |
| Minor | `0.1.1 → 0.2.0` | New backward-compatible features |
| Major | `0.1.1 → 1.0.0` | Breaking API changes |

### Step 3 — Commit the version bump

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.1.2"
git push origin main
```

### Step 4 — Tag and push

```bash
git tag v0.1.2
git push origin v0.1.2
```

Pushing the tag triggers `publish.yml` automatically.

### Step 5 — Confirm the release

Check the `Publish to PyPI` workflow in GitHub Actions, then verify the new version on PyPI:

```text
https://pypi.org/project/agent-wave/
```

---

## Pinned Action SHA Strategy

### Why pin SHAs instead of using tags?

Floating tags (e.g. `@v4`) carry a supply-chain risk: the action maintainer — or an attacker who compromises the repository — can silently move the tag to a malicious commit, causing CI to execute arbitrary code.

All actions in this project are pinned to a specific commit SHA:

```yaml
# Unsafe (floating tag)
uses: actions/checkout@v4

# Safe (pinned SHA)
uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4
```

### Current action versions

| Action | Pinned SHA | Version |
|--------|------------|---------|
| `actions/checkout` | `34e114876b0b11c390a56381ad16ebd13914f8d5` | v4 |
| `astral-sh/setup-uv` | `e58605a9b6da7c637471fab8847a5e5a6b8df081` | v5 |
| `actions/setup-python` | `a26af69be951a213d495a4c3e4e4022e16d87065` | v5 |
| `pypa/gh-action-pypi-publish` | `ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e` | — |

### How to upgrade an action

1. Find the new release on the action's GitHub Releases page and copy the commit SHA
2. Update the SHA in both `.github/workflows/ci.yml` and `.github/workflows/publish.yml`
3. Open a PR so CI validates the change before merging

---

## Troubleshooting

### CI fails on `ruff format`

Run auto-format locally and commit the result:

```bash
uv run ruff format .
git add -u && git commit -m "style: apply ruff format"
```

### CI fails on docstring coverage

Find which functions are missing docstrings:

```bash
uv run interrogate agvv --fail-under=100
```

Add docstrings to all reported functions, classes, and modules.

### Publish fails: version mismatch

Verify that `pyproject.toml` version matches the tag you pushed:

```bash
grep '^version' pyproject.toml
```

If the tag was created with the wrong version, delete it and re-tag after fixing `pyproject.toml`:

```bash
git tag -d v0.1.2
git push origin :refs/tags/v0.1.2
# fix pyproject.toml, commit, then re-tag
```

### Run CI checks locally

```bash
uv run ruff check .
uv run ruff format --check .
uv run interrogate agvv --fail-under=100 --quiet
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing
```

To enable the pre-commit hook (runs docstring check on every commit):

```bash
git config core.hooksPath .githooks
```
