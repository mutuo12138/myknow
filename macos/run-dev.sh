#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This development launcher must run on macOS." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -x .venv/bin/python ]]; then
  echo "Virtual environment not found. Run ./macos/bootstrap.sh first." >&2
  exit 1
fi

source .venv/bin/activate
exec python desktop.py --native
