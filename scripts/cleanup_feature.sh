#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <project_name> <feature_branch> [base_dir]"
  exit 1
fi

PROJECT_NAME="$1"
FEATURE="$2"
BASE_DIR="${3:-$HOME/code}"

shift 3 || true
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec uv run --directory "$ROOT_DIR" orch feature cleanup "$PROJECT_NAME" "$FEATURE" --base-dir "$BASE_DIR" "$@"
