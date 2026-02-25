#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <existing_repo_path> <project_name> [base_dir]"
  exit 1
fi

EXISTING_REPO="$(cd "$1" && pwd)"
PROJECT_NAME="$2"
BASE_DIR="${3:-$HOME/code}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec uv run --directory "$ROOT_DIR" agvv project adopt "$EXISTING_REPO" "$PROJECT_NAME" --base-dir "$BASE_DIR"
