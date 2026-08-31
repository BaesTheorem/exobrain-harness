#!/bin/bash
# Pin the Claude Code CLI to ONE path that never changes, so its TCC grants stop
# evaporating every time it auto-updates.
#
# THE PROBLEM. The `claude` binary is a bare Mach-O with no bundle, so TCC keys
# every permission it holds by PATH (identifier_type=Path in tccd's log). The
# native installer drops each release at its own versioned path:
#
#     ~/.local/share/claude/versions/2.1.250
#     ~/.local/share/claude/versions/2.1.251   <- new path = new TCC identity
#
# The CLI updates roughly daily, so roughly daily every grant it holds is
# addressed to a path nothing runs from any more. Full Disk Access is the one
# that hurts: it lives in the SYSTEM database, which is SIP-protected, so no
# script can carry it -- only Alex, by hand, in System Settings, every release.
# Miss a day and the "would like to access data from other apps" dialog starts
# firing, once per app-data directory any routine touches. (2026-08-31: eleven
# prompts before lunch.)
#
# THE FIX. Keep a real copy of the newest release at a path that never moves:
#
#     ~/.local/share/claude/stable/claude
#
# and point ~/.local/bin/claude (what `command -v claude` resolves, and what the
# Console, the routines, and the autoupdater all follow) at that copy. Grant Full
# Disk Access to the stable path ONCE and it holds forever, because TCC
# re-evaluates the grant's stored code requirement against whatever binary is at
# the path, and the requirement macOS writes for this binary is
# version-independent:
#
#     identifier "com.anthropic.claude-code" and anchor apple generic
#       and certificate leaf[subject.OU] = Q6L2SF6YDW
#
# Any Anthropic-signed release satisfies it. Same argument tcc_carry_forward.py
# makes for the user-database grants; this just extends it to the one grant that
# script cannot write.
#
# A symlink would NOT work. tccd records the resolved target, so a symlink at a
# stable path still presents the versioned identity. It has to be a real file.
#
# INVARIANTS
#   - NEVER install a binary that fails `codesign --verify --strict -R` against
#     the canonical Anthropic requirement. An unverified copy inheriting Full
#     Disk Access is the whole thing this must not do.
#   - Replace by rename, never by writing in place. `mv` swaps the directory
#     entry; processes already running the old inode keep running.
#   - NEVER pin the versions directory contents by name. The filename IS the
#     version and changes every release.

set -uo pipefail

VERSIONS="$HOME/.local/share/claude/versions"
STABLE_DIR="$HOME/.local/share/claude/stable"
STABLE="$STABLE_DIR/claude"
LINK="$HOME/.local/bin/claude"
REQ='identifier "com.anthropic.claude-code" and anchor apple generic and certificate leaf[subject.OU] = Q6L2SF6YDW'
LOG="$HOME/Library/Logs/exobrain/claude-stable-path.log"

mkdir -p "$STABLE_DIR" "$(dirname "$LOG")"
ts() { date '+%Y-%m-%d %H:%M:%S'; }
say() { echo "$(ts) $*" >>"$LOG"; }

# The updater rewrites the ~/.local/bin symlink a beat after it lands the new
# binary, and WatchPaths fires on the binary. Let it finish before we repoint,
# or it clobbers us and the next run has to undo it.
[ "${1:-}" = "--now" ] || sleep 5

# Newest release on disk, by version order rather than mtime: a rollback rewrites
# mtimes but never makes an older release the current one.
NEWEST=$(ls "$VERSIONS" 2>/dev/null | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
if [ -z "$NEWEST" ] || [ ! -x "$VERSIONS/$NEWEST" ]; then
  say "FAIL no installed version found under $VERSIONS"
  exit 1
fi
SRC="$VERSIONS/$NEWEST"

# Only copy when the content actually differs. 197MB per release is cheap but
# not free, and a no-op run must not churn the file a running CLI is mapped to.
if [ -f "$STABLE" ] && cmp -s "$SRC" "$STABLE"; then
  COPIED=no
else
  if ! codesign --verify --strict -R="$REQ" "$SRC" 2>>"$LOG"; then
    say "REFUSED $NEWEST does not satisfy the Anthropic code requirement -- stable path left alone"
    exit 1
  fi
  TMP="$STABLE_DIR/.claude.incoming.$$"
  cp "$SRC" "$TMP" || { say "FAIL copy of $NEWEST"; rm -f "$TMP"; exit 1; }
  # Verify the COPY, not just the source: a truncated write would otherwise
  # inherit the grant.
  if ! codesign --verify --strict -R="$REQ" "$TMP" 2>>"$LOG"; then
    say "REFUSED copy of $NEWEST failed verification after write"
    rm -f "$TMP"
    exit 1
  fi
  chmod 755 "$TMP"
  mv -f "$TMP" "$STABLE"
  COPIED=yes
  say "installed $NEWEST at the stable path"
fi

# Repoint whatever `claude` resolves to. Idempotent.
CURRENT_TARGET=$(readlink "$LINK" 2>/dev/null || true)
if [ "$CURRENT_TARGET" != "$STABLE" ]; then
  mkdir -p "$(dirname "$LINK")"
  ln -sfn "$STABLE" "$LINK"
  say "repointed $LINK -> $STABLE (was ${CURRENT_TARGET:-not a symlink})"
  RELINKED=yes
else
  RELINKED=no
fi

[ "$COPIED" = no ] && [ "$RELINKED" = no ] && say "OK stable path already current ($NEWEST)"

# Re-point the user-database grants at the stable path too, now that it is the
# live identity. Runs under its own FDA-holding interpreter, so this read is
# silent; see tcc_carry_forward.py.
CARRY="$HOME/Documents/Exobrain harness/maintenance/venv/bin/mist-tcc-python3"
[ -x "$CARRY" ] && "$CARRY" "$HOME/Documents/Exobrain harness/maintenance/tcc_carry_forward.py" --prune >>"$LOG" 2>&1

exit 0
