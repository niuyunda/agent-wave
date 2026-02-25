#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <project_name> [base_dir]"
  exit 1
fi

PROJECT_NAME="$1"
BASE_DIR="${2:-$HOME/code}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec uv run --directory "$ROOT_DIR" agvv project init "$PROJECT_NAME" --base-dir "$BASE_DIR"
