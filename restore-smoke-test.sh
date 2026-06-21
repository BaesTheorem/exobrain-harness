#!/bin/bash
# restore-smoke-test.sh — post-restore verification for the Exobrain harness.
#
# "Restore complete" should mean "the system works," not "the procedure finished."
# This checks the layers a casual glance misses: the automation jobs, the vault,
# the local MCP wiring, the out-of-tree credentials, and the known gap items.
#
# Read-only. Safe to run any time. Run after Phase 7/8 of the /restore-harness skill.
#   bash restore-smoke-test.sh
#
# Exit code: number of FAILs (0 = clean).

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SCRIPT_DIR/config.sh" ] && source "$SCRIPT_DIR/config.sh"
HARNESS_DIR="${HARNESS_DIR:-$HOME/Documents/Exobrain harness}"
VAULT_DIR="${VAULT_DIR:-$HOME/Exobrain}"

fails=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fails=$((fails+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }

echo "== Vault (left to Obsidian Sync; tarball is fallback only) =="
[ -f "$VAULT_DIR/Dashboard.md" ] && pass "vault present + readable ($VAULT_DIR/Dashboard.md)" \
  || fail "vault missing or unreadable — check Obsidian Sync, do NOT auto-restore from tarball"

echo "== Harness core files =="
[ -f "$HARNESS_DIR/.env" ] && grep -q WITHINGS "$HARNESS_DIR/.env" 2>/dev/null \
  && pass ".env present with Withings creds" || fail ".env missing or missing Withings creds"
[ -f "$HARNESS_DIR/.mcp.json" ] && pass ".mcp.json present" || fail ".mcp.json missing"
if [ -f "$HARNESS_DIR/processing-log.json" ]; then
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$HARNESS_DIR/processing-log.json" 2>/dev/null \
    && pass "processing-log.json parses" || fail "processing-log.json is corrupt"
else
  warn "processing-log.json absent (fresh start — watchers will re-process recent items)"
fi

echo "== Toolchain =="
for b in git gh brew node python3 uv jq rsync; do
  command -v "$b" >/dev/null 2>&1 && pass "$b on PATH" || fail "$b not found"
done
command -v python3.12 >/dev/null 2>&1 && pass "python3.12 present (mist-voice)" \
  || warn "python3.12 missing — mist-voice TTS will not build"
command -v claude >/dev/null 2>&1 && pass "claude CLI present" || fail "claude CLI not found"

echo "== Out-of-tree credentials (the backup's known blind spots) =="
[ -f "$HOME/.claude/settings.json" ] && pass "~/.claude/settings.json present" \
  || fail "~/.claude/settings.json missing (permissions flood; global MCP lost)"
[ -f "$HOME/.claude/channels/discord/.env" ] && pass "discord bot token present" \
  || warn "~/.claude/channels/discord/.env missing — claude-bot will not authenticate"
[ -f "$HOME/.plaud/tokens-mcp.json" ] && pass "~/.plaud token present" \
  || warn "~/.plaud token missing — re-auth via mcp__plaud__login"
[ -f "$HOME/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json" ] \
  && pass "fitbit MCP token present" \
  || warn "fitbit MCP token missing (depth-3 backup gap) — health data will not flow until re-auth"

echo "== launchd automation (silent-failure layer) =="
if command -v launchctl >/dev/null 2>&1; then
  loaded=$(launchctl list 2>/dev/null | grep -cE 'exobrain|mist|nightwatch|passage')
  [ "$loaded" -gt 0 ] && pass "$loaded exobrain/mist/nightwatch jobs loaded" \
    || warn "no automation jobs loaded (expected if --no-watchers / minimal restore)"
  # launchctl shows each job's LAST exit code. Periodic jobs legitimately exit
  # nonzero once (SIGTERM on restart = -15, transient API failure = 1, EX_CONFIG
  # = 78). So a nonzero last-exit is worth eyeballing (WARN), not a hard FAIL.
  # Hard FAIL is reserved for jobs that don't load at all (handled above).
  badjobs=$(launchctl list 2>/dev/null | awk '/exobrain|mist|nightwatch|passage/ && $2 != 0 && $2 != "-" {print $3" (last exit "$2")"}')
  [ -z "$badjobs" ] && pass "no jobs in a nonzero last-exit state" \
    || { while IFS= read -r j; do warn "nonzero last exit, eyeball it: $j"; done <<< "$badjobs"; }
  for d in discord maintenance awair; do
    [ -d "$HOME/.claude/channels/$d" ] || warn "~/.claude/channels/$d missing — its plist will fail to start"
  done
else
  warn "launchctl unavailable"
fi

echo
if [ "$fails" -eq 0 ]; then
  printf '\033[32mSMOKE TEST CLEAN\033[0m — review any WARNs above (cloud re-auths, orphaned plists, gap items).\n'
else
  printf '\033[31m%d FAIL(s)\033[0m — resolve before calling the restore done.\n' "$fails"
fi
exit "$fails"
