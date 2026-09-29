#!/usr/bin/env bash
# Double-click on macOS (or run ./"Start Second Brain.command" on Linux) to open your Second Brain.
# First run creates a private Python environment in .venv and installs everything (about a minute).
set -e
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Enter to close..." _; exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Second Brain (about a minute)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e ".[excel]"
  .venv/bin/python -m pip install --quiet extract-msg >/dev/null 2>&1 || echo "(Optional Outlook .msg support could not be installed - everything else works.)"
fi

echo "Starting Second Brain. Your browser will open at http://localhost:8787"
echo "Keep this window open while you use it; close it (or press Ctrl+C) to stop."
exec .venv/bin/python -m secondbrain ui
