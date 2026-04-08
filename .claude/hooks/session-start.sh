#!/bin/bash
# Exobrain session startup hook — date context + system health check

HARNESS="/Users/alexhedtke/Documents/Exobrain harness"
VAULT="/Users/alexhedtke/Documents/Exobrain"

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

# Plaud folder
if [ -d "$VAULT/Plaud" ]; then
  echo "OK: Plaud folder"
else
  echo "FAIL: Plaud folder missing"
  ISSUES=$((ISSUES + 1))
fi

# Supernote folder
if [ -d "/Users/alexhedtke/My Drive/Supernote/Note" ]; then
  echo "OK: Supernote folder"
else
  echo "FAIL: Supernote folder not accessible"
  ISSUES=$((ISSUES + 1))
fi

# MCP config
if [ -f "$HARNESS/.mcp.json" ]; then
  # Check each server is defined
  for SERVER in things3 fitbit withings weather; do
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

# Fitbit token
if [ -f "/Users/alexhedtke/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json" ]; then
  echo "OK: Fitbit token"
else
  echo "WARN: Fitbit token missing — may need re-auth"
  ISSUES=$((ISSUES + 1))
fi

# Withings credentials
if [ -f "$HARNESS/.env" ]; then
  echo "OK: Withings credentials (.env)"
else
  echo "FAIL: Withings .env missing"
  ISSUES=$((ISSUES + 1))
fi

# launchd jobs
PLAUD_LOADED=$(launchctl list 2>/dev/null | grep -c "plaud-watcher")
NOTES_LOADED=$(launchctl list 2>/dev/null | grep -c "apple-notes-sync")
DIGEST_LOADED=$(launchctl list 2>/dev/null | grep -c "discord-digest")

if [ "$PLAUD_LOADED" -ge 1 ]; then
  echo "OK: launchd plaud-watcher"
else
  echo "FAIL: launchd plaud-watcher not loaded"
  ISSUES=$((ISSUES + 1))
fi

if [ "$NOTES_LOADED" -ge 1 ]; then
  echo "OK: launchd apple-notes-sync"
else
  echo "FAIL: launchd apple-notes-sync not loaded"
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

# Discord digest freshness
DIGEST="$HARNESS/discord-digest.json"
if [ -f "$DIGEST" ]; then
  AGE=$(( ($(date +%s) - $(stat -f %m "$DIGEST")) / 3600 ))
  if [ "$AGE" -le 24 ]; then
    echo "OK: Discord digest (${AGE}h old)"
  else
    echo "WARN: Discord digest stale (${AGE}h old)"
  fi
else
  echo "WARN: Discord digest missing"
fi

# Summary
echo ""
if [ "$ISSUES" -eq 0 ]; then
  echo "All systems nominal."
else
  echo "$ISSUES issue(s) detected — check above."
fi

# === SESSION MEMORY ===
MEMORY_DIR="$HARNESS/.claude/session-memory"
if [ -d "$MEMORY_DIR" ]; then
  # Get the 3 most recent session memory files
  RECENT=$(ls -t "$MEMORY_DIR"/*.md 2>/dev/null | head -3)
  if [ -n "$RECENT" ]; then
    echo ""
    echo "=== Recent Session Memory ==="
    for f in $RECENT; do
      FNAME=$(basename "$f")
      echo ""
      echo "--- $FNAME ---"
      cat "$f"
    done
    echo ""
    echo "=== End Session Memory ==="
  fi
fi
