#!/bin/bash
# Exobrain session startup hook — date context + system health check

SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
source "$SCRIPT_DIR/config.sh"
HARNESS="$HARNESS_DIR"
VAULT="$VAULT_DIR"

# === DATE + LOGICAL DAY ===
HOUR=$(date +%H)
if [ "$HOUR" -lt 2 ]; then
  LOGICAL_DATE=$(date -v-1d +"%A, %B %-d, %Y")
  echo "Date: $(date +"%A, %B %-d, %Y %I:%M %p") — logical day: $LOGICAL_DATE (pre-2AM)"
else
  echo "Date: $(date +"%A, %B %-d, %Y %I:%M %p")"
fi

# === SYSTEM HEALTH ===
echo ""
ISSUES=0

# Google Drive / Obsidian vault
if [ -d "$VAULT" ]; then
  echo "OK: Obsidian vault"
else
  echo "FAIL: Obsidian vault not accessible (Google Drive not mounted?)"
  ISSUES=$((ISSUES + 1))
fi

# Plaud folder (in Google Drive)
if [ -d "$HOME/My Drive/Plaud" ]; then
  echo "OK: Plaud folder"
else
  echo "FAIL: Plaud folder missing (Google Drive not mounted?)"
  ISSUES=$((ISSUES + 1))
fi

# Supernote folder
if [ -d "$GDRIVE_SUPERNOTE" ]; then
  echo "OK: Supernote folder"
else
  echo "FAIL: Supernote folder not accessible"
  ISSUES=$((ISSUES + 1))
fi

# MCP config
if [ -f "$HARNESS/.mcp.json" ]; then
  # Check each server is defined
  for SERVER in things3 fitbit withings; do
    if python3 -c "import json; d=json.load(open('$HARNESS/.mcp.json')); assert '$SERVER' in d.get('mcpServers',{})" 2>/dev/null; then
      echo "OK: MCP $SERVER configured"
    else
      echo "FAIL: MCP $SERVER missing from .mcp.json"
      ISSUES=$((ISSUES + 1))
    fi
  done
else
  echo "FAIL: .mcp.json missing"
  ISSUES=$((ISSUES + 1))
fi

# Fitbit token existence + freshness
if [ -f "$FITBIT_TOKEN" ]; then
  FITBIT_STATUS=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(open('$FITBIT_TOKEN'))
    exp = datetime.fromisoformat(d['expires_at'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    hours_left = (exp - now).total_seconds() / 3600
    if hours_left < 0:
        print(f'WARN: Fitbit token expired {-hours_left:.0f}h ago — needs re-auth')
    elif hours_left < 1:
        print(f'WARN: Fitbit token expires in {hours_left*60:.0f}m — refresh soon')
    else:
        print(f'OK: Fitbit token (valid for {hours_left:.0f}h)')
except Exception as e:
    print(f'WARN: Fitbit token unreadable — {e}')
" 2>/dev/null)
  echo "$FITBIT_STATUS"
  if echo "$FITBIT_STATUS" | grep -q "WARN"; then
    ISSUES=$((ISSUES + 1))
  fi
else
  echo "WARN: Fitbit token missing — may need re-auth"
  ISSUES=$((ISSUES + 1))
fi

# Withings credentials — verifies refresh token is present in .mcp.json (preferred)
# or .env. Withings uses a long-lived refresh token; access tokens are minted on
# demand by the MCP server, so there's no on-disk expiry to inspect here.
WITHINGS_OK=0
if [ -f "$HARNESS/.mcp.json" ] && python3 -c "import json,sys; d=json.load(open('$HARNESS/.mcp.json')); sys.exit(0 if d.get('mcpServers',{}).get('withings',{}).get('env',{}).get('WITHINGS_REFRESH_TOKEN') else 1)" 2>/dev/null; then
  WITHINGS_OK=1
elif [ -f "$HARNESS/.env" ] && grep -q "WITHINGS_REFRESH_TOKEN" "$HARNESS/.env" 2>/dev/null; then
  WITHINGS_OK=1
fi
if [ "$WITHINGS_OK" -eq 1 ]; then
  echo "OK: Withings credentials (refresh token present)"
else
  echo "WARN: Withings refresh token missing — may need re-auth"
  ISSUES=$((ISSUES + 1))
fi

# launchd jobs
PLAUD_LOADED=$(launchctl list 2>/dev/null | grep -c "plaud-watcher")
DIGEST_LOADED=$(launchctl list 2>/dev/null | grep -c "discord-digest")

if [ "$PLAUD_LOADED" -ge 1 ]; then
  echo "OK: launchd plaud-watcher"
else
  echo "FAIL: launchd plaud-watcher not loaded"
  ISSUES=$((ISSUES + 1))
fi

if [ "$DIGEST_LOADED" -ge 1 ]; then
  echo "OK: launchd discord-digest"
else
  echo "FAIL: launchd discord-digest not loaded"
  ISSUES=$((ISSUES + 1))
fi

SUPERNOTE_LOADED=$(launchctl list 2>/dev/null | grep -c "supernote-watcher")
if [ "$SUPERNOTE_LOADED" -ge 1 ]; then
  echo "OK: launchd supernote-watcher"
else
  echo "FAIL: launchd supernote-watcher not loaded"
  ISSUES=$((ISSUES + 1))
fi

# Watcher health — check for recent failures (last 24h)
for WATCHER in supernote plaud; do
  FAIL_LOG="/tmp/exobrain-${WATCHER}-failures.log"
  if [ -f "$FAIL_LOG" ]; then
    FAIL_AGE=$(( ($(date +%s) - $(stat -f %m "$FAIL_LOG")) / 3600 ))
    if [ "$FAIL_AGE" -le 24 ]; then
      LAST_FAIL=$(tail -2 "$FAIL_LOG")
      echo "WARN: ${WATCHER}-watcher has recent failures (${FAIL_AGE}h ago)"
      echo "  $LAST_FAIL"
      ISSUES=$((ISSUES + 1))
    fi
  fi
done

# Processing log integrity
LOG="$HARNESS/processing-log.json"
if [ -f "$LOG" ]; then
  if python3 -c "import json; json.load(open('$LOG'))" 2>/dev/null; then
    TOTAL=$(python3 -c "import json; print(len(json.load(open('$LOG'))))" 2>/dev/null)
    echo "OK: Processing log ($TOTAL entries)"
  else
    echo "FAIL: Processing log — corrupt JSON"
    ISSUES=$((ISSUES + 1))
  fi
else
  echo "FAIL: Processing log missing"
  ISSUES=$((ISSUES + 1))
fi

# Discord digest freshness — read last_successful_fetch from JSON (file mtime
# can be misleading because a failed fetch may rewrite the file with old data).
# See discord/README.md for the contract.
DIGEST="$HARNESS/discord/discord-digest.json"
if [ -f "$DIGEST" ]; then
  DIGEST_AGE=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(open('$DIGEST'))
    ts = d.get('last_successful_fetch') or d.get('fetched_at')
    if not ts:
        print('WARN: Discord digest has no last_successful_fetch field')
        sys.exit(0)
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    age_h = int((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    if age_h <= 24:
        print(f'OK: Discord digest (last successful fetch {age_h}h ago)')
    else:
        print(f'WARN: Discord digest stale (last successful fetch {age_h}h ago)')
except Exception as e:
    print(f'WARN: Discord digest unreadable — {e}')
" 2>/dev/null)
  echo "$DIGEST_AGE"
  if echo "$DIGEST_AGE" | grep -q "WARN"; then
    ISSUES=$((ISSUES + 1))
  fi
else
  echo "WARN: Discord digest missing"
  ISSUES=$((ISSUES + 1))
fi

# Summary
echo ""
if [ "$ISSUES" -eq 0 ]; then
  echo "All systems nominal."
else
  echo "$ISSUES issue(s) detected — check above."
fi

# === SESSION MEMORY ===
# Load: 3 most recent daily digests (cross-day context, ~150 words each) +
# 3 most recent individual session memories (granular recent state).
# Digests are filtered out of the session list to avoid double-counting.
MEMORY_DIR="$SESSION_MEMORY_DIR"
if [ -d "$MEMORY_DIR" ]; then
  RECENT_DIGESTS=$(ls -t "$MEMORY_DIR"/*_DIGEST.md 2>/dev/null | head -3)
  RECENT_SESSIONS=$(ls -t "$MEMORY_DIR"/*.md 2>/dev/null | grep -v '_DIGEST\.md$' | head -3)

  if [ -n "$RECENT_DIGESTS" ] || [ -n "$RECENT_SESSIONS" ]; then
    echo ""
    echo "=== Recent Daily Digests ==="
    if [ -n "$RECENT_DIGESTS" ]; then
      while IFS= read -r f; do
        FNAME=$(basename "$f")
        echo ""
        echo "--- $FNAME ---"
        cat "$f"
      done <<< "$RECENT_DIGESTS"
    else
      echo "(none yet — first 11pm consolidator run will generate one)"
    fi
    echo ""
    echo "=== Recent Session Memory ==="
    if [ -n "$RECENT_SESSIONS" ]; then
      while IFS= read -r f; do
        FNAME=$(basename "$f")
        echo ""
        echo "--- $FNAME ---"
        cat "$f"
      done <<< "$RECENT_SESSIONS"
    fi
    echo ""
    echo "=== End Session Memory ==="
  fi
fi

# === VAULT SNAPSHOT ===
SNAPSHOT_FILE="$HOME/.claude/projects/-Users-alexhedtke-Documents-Exobrain-harness/vault-snapshot.md"
if [ -f "$SNAPSHOT_FILE" ]; then
  AGE_HOURS=$(( ($(date +%s) - $(stat -f %m "$SNAPSHOT_FILE")) / 3600 ))
  echo ""
  echo "=== Vault Snapshot (${AGE_HOURS}h old) ==="
  cat "$SNAPSHOT_FILE"
  echo ""
  echo "=== End Vault Snapshot ==="
  if [ "$AGE_HOURS" -gt 36 ]; then
    echo "WARN: vault-snapshot stale (>36h). Check com.exobrain.vault-snapshot launchd job."
  fi
else
  echo ""
  echo "WARN: vault-snapshot missing. Run scripts/vault-snapshot.sh or check launchd."
fi
