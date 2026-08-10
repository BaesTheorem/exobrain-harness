#!/bin/bash
# PostToolUse hook: lint + type-check the Python file an agent just edited,
# and feed any errors straight back to the agent (exit 2 -> stderr to Claude).
#
# Why: this repo is written by many agent sessions with no shared memory.
# Rules that live in prose get skipped by low-context sessions; rules that
# arrive as an error message seconds after the edit get fixed. See
# pyproject.toml for what is enforced and why.
#
# Design constraints:
#   - Fail open. A missing tool or unparseable payload must never block edits.
#   - Per-file only. Full-repo pyright OOMs node on this 8GB machine.
#   - Fast. ruff is ms; pyright single-file is ~1-2s.

set -u

RUFF="$HOME/.local/bin/ruff"
PYRIGHT="$HOME/.npm-global/bin/pyright"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

payload="$(cat)"

file_path="$(printf '%s' "$payload" | /usr/bin/python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get("tool_input", {}).get("file_path", ""))
except Exception:
    pass
' 2>/dev/null)"

# Only Python files that still exist; skip scratch space.
[ -n "$file_path" ] || exit 0
case "$file_path" in
    *.py) ;;
    *) exit 0 ;;
esac
[ -f "$file_path" ] || exit 0
case "$file_path" in
    "$REPO_DIR"/tmp/*) exit 0 ;;
esac

errors=""

if [ -x "$RUFF" ]; then
    ruff_out="$(cd "$REPO_DIR" && "$RUFF" check --output-format concise "$file_path" 2>&1)"
    if [ $? -ne 0 ] && [ -n "$ruff_out" ]; then
        errors="ruff:
$ruff_out"
    fi
fi

if [ -x "$PYRIGHT" ]; then
    pyright_out="$(cd "$REPO_DIR" && "$PYRIGHT" --project "$REPO_DIR" "$file_path" 2>&1)"
    if [ $? -ne 0 ] && [ -n "$pyright_out" ]; then
        # Keep only the diagnostic lines; drop the banner/summary noise.
        pyright_diag="$(printf '%s\n' "$pyright_out" | grep -E ' - (error|warning): ' | head -30)"
        if [ -n "$pyright_diag" ]; then
            errors="$errors

pyright:
$pyright_diag"
        fi
    fi
fi

boundaries_out="$(cd "$REPO_DIR" && python3 checks/check_boundaries.py "$file_path" 2>&1)"
if [ $? -ne 0 ] && [ -n "$boundaries_out" ]; then
    errors="$errors

$boundaries_out"
fi

if [ -n "$errors" ]; then
    {
        echo "post-edit check failed for $file_path"
        echo "$errors"
        echo
        echo "Fix these before moving on. If a finding is intentional, add a noqa with a reason (see pyproject.toml)."
    } >&2
    exit 2
fi

exit 0
