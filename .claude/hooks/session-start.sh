#!/bin/bash
# Exobrain session startup hook -- date context + system health check

SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
source "$SCRIPT_DIR/config.sh"
HARNESS="$HARNESS_DIR"
VAULT="$VAULT_DIR"

# === DATE + LOGICAL DAY ===
HOUR=$(date +%H)
if [ "$HOUR" -lt 2 ]; then
  LOGICAL_DATE=$(date -v-1d +"%A, %B %-d, %Y")
  echo "Date: $(date +"%A, %B %-d, %Y %I:%M %p") -- logical day: $LOGICAL_DATE (pre-2AM)"
else
  echo "Date: $(date +"%A, %B %-d, %Y %I:%M %p")"
fi

# === PENDING ACTION: LinkedIn job lane backfill ===
# Raised by the headless daily job scan (run-job-scan.sh) when it couldn't reach
# the LinkedIn MCP. Surface it loudly and first so this interactive session
# backfills that lane before anything else. Cleared by a later successful scan
# (headless or interactive) or by rm'ing the file once the lane has run.
JOBSCAN_SENTINEL="$HARNESS/job-search/.linkedin-scan-pending"
if [ -f "$JOBSCAN_SENTINEL" ]; then
  MISS_DATE=$(head -1 "$JOBSCAN_SENTINEL" 2>/dev/null)
  PENDING_DAYS=$(( ($(date +%s) - $(stat -f %m "$JOBSCAN_SENTINEL")) / 86400 ))
  echo ""
  echo "‼️  ACTION FIRST -- LinkedIn job lane pending (missed ${MISS_DATE:-recently}, ${PENDING_DAYS}d ago)"
  echo "    The headless daily job scan could not reach the LinkedIn MCP, so that"
  echo "    discovery lane was skipped. Before anything else this session, run the"
  echo "    /job-search LinkedIn lane (search_jobs across rotating angles → JD-read →"
  echo "    4 hard gates → dedup vs Job Listings/ → write listing notes), then clear it:"
  echo "      rm \"$JOBSCAN_SENTINEL\""
fi

# === PENDING ACTION: Gmail job-alert lane backfill ===
# Same mechanism as the LinkedIn sentinel above, raised when the headless scan
# couldn't reach the claude.ai Gmail connector. Alert emails decay in ~3 days,
# so this lane rots fast when it silently misses.
GMAILSCAN_SENTINEL="$HARNESS/job-search/.gmail-scan-pending"
if [ -f "$GMAILSCAN_SENTINEL" ]; then
  GM_MISS_DATE=$(head -1 "$GMAILSCAN_SENTINEL" 2>/dev/null)
  GM_PENDING_DAYS=$(( ($(date +%s) - $(stat -f %m "$GMAILSCAN_SENTINEL")) / 86400 ))
  echo ""
  echo "‼️  ACTION FIRST -- Gmail job-alert lane pending (missed ${GM_MISS_DATE:-recently}, ${GM_PENDING_DAYS}d ago)"
  echo "    The headless daily job scan could not reach the claude.ai Gmail MCP, so"
  echo "    the alert-email discovery lane (the pipeline's highest-yield lane) was"
  echo "    skipped. Run it early this session per the skill's Gmail method"
  echo "    (search_threads newer_than:4d → get_thread → harvest ALL roles per email"
  echo "    → gates → listing notes), then clear it:"
  echo "      rm \"$GMAILSCAN_SENTINEL\""
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
# `[ -d ]` only stats, which TCC still allows after a Claude Code upgrade
# invalidates the Google Drive grant. List instead, so a blocked readdir fails loudly.
if ls "$HOME/My Drive/Plaud" >/dev/null 2>&1; then
  echo "OK: Plaud folder"
elif [ -d "$HOME/My Drive/Plaud" ]; then
  echo "FAIL: Plaud folder unreadable -- grant this Claude Code binary access to Google Drive"
  ISSUES=$((ISSUES + 1))
else
  echo "FAIL: Plaud folder missing (Google Drive not mounted?)"
  ISSUES=$((ISSUES + 1))
fi

# Supernote folder
if ls "$GDRIVE_SUPERNOTE" >/dev/null 2>&1; then
  echo "OK: Supernote folder"
elif [ -d "$GDRIVE_SUPERNOTE" ]; then
  echo "FAIL: Supernote folder unreadable -- grant this Claude Code binary access to Google Drive"
  ISSUES=$((ISSUES + 1))
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
        print(f'WARN: Fitbit token expired {-hours_left:.0f}h ago -- needs re-auth')
    elif hours_left < 1:
        print(f'WARN: Fitbit token expires in {hours_left*60:.0f}m -- refresh soon')
    else:
        print(f'OK: Fitbit token (valid for {hours_left:.0f}h)')
except Exception as e:
    print(f'WARN: Fitbit token unreadable -- {e}')
" 2>/dev/null)
  echo "$FITBIT_STATUS"
  if echo "$FITBIT_STATUS" | grep -q "WARN"; then
    ISSUES=$((ISSUES + 1))
  fi
else
  echo "WARN: Fitbit token missing -- may need re-auth"
  ISSUES=$((ISSUES + 1))
fi

# Withings credentials -- verifies refresh token is present in .mcp.json (preferred)
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
  echo "WARN: Withings refresh token missing -- may need re-auth"
  ISSUES=$((ISSUES + 1))
fi

# Nest (SDM) auth health. This used to warn off token.json's mtime on the
# theory that a "Testing"-status consent screen expires the refresh token after
# 7 days. That predicted a dead token at 11 days on 2026-08-05; a live SDM call
# returned all 4 devices, so the heuristic was just wrong and cried wolf daily.
# Check the OUTCOME instead: nest-poll runs every 300s and rewrites
# nest-data.json only on a successful authenticated fetch, so that file's mtime
# is proof the token worked recently. Stale data = real breakage (expired token,
# dead poller, no network); token age on its own is not.
NEST_TOKEN="$HOME/Documents/claude-home/integrations/nest/token.json"
NEST_DATA="$HOME/Documents/claude-home/integrations/nest/nest-data.json"
if [ ! -f "$NEST_TOKEN" ]; then
  echo "WARN: Nest token missing -- run nest-auth.py to reconnect HVAC"
  ISSUES=$((ISSUES + 1))
elif [ -f "$NEST_DATA" ]; then
  NEST_DATA_AGE_M=$(( ($(date +%s) - $(stat -f %m "$NEST_DATA")) / 60 ))
  if [ "$NEST_DATA_AGE_M" -gt 60 ]; then
    echo "WARN: Nest data stale (${NEST_DATA_AGE_M}m old; nest-poll runs every 5m) -- check token (nest-auth.py) and com.exobrain.nest-poll"
    ISSUES=$((ISSUES + 1))
  else
    echo "OK: Nest auth (successful poll ${NEST_DATA_AGE_M}m ago)"
  fi
else
  echo "WARN: Nest data missing -- nest-poll has never succeeded"
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

AWAIR_LOADED=$(launchctl list 2>/dev/null | grep -c "awair-co2-watcher")
if [ "$AWAIR_LOADED" -ge 1 ]; then
  echo "OK: launchd awair-co2-watcher"
else
  echo "FAIL: launchd awair-co2-watcher not loaded"
  ISSUES=$((ISSUES + 1))
fi

THINGS3SYNC_LOADED=$(launchctl list 2>/dev/null | grep -c "things3-sync")
if [ "$THINGS3SYNC_LOADED" -ge 1 ]; then
  echo "OK: launchd things3-sync"
else
  echo "FAIL: launchd things3-sync not loaded"
  ISSUES=$((ISSUES + 1))
fi

BACKUP_LOADED=$(launchctl list 2>/dev/null | grep -c "com.exobrain.backup")
if [ "$BACKUP_LOADED" -ge 1 ]; then
  echo "OK: launchd backup"
else
  echo "FAIL: launchd backup not loaded"
  ISSUES=$((ISSUES + 1))
fi

# iMessage sync -- the launchd job snapshots chat.db into imessage/cache/ under a
# stable FDA-granted interpreter so skills read the cache WITHOUT Full Disk Access.
# It fails SILENTLY if FDA isn't granted to the plist's python3 (exit 2 / "Operation
# not permitted"), leaving briefings/CRM/winddown reading an empty cache. Check the
# job's last exit code AND cache freshness (sync runs every 15m). See imessage/README.md.
# launchctl list columns: PID  LAST_EXIT  LABEL.
IMSG_EXIT=$(launchctl list 2>/dev/null | awk '$3 == "com.exobrain.imessage-sync" {print $2}')
IMSG_CACHE="$HARNESS/imessage/cache/chat.db"
if [ -z "$IMSG_EXIT" ]; then
  echo "WARN: launchd imessage-sync not loaded -- iMessage data unavailable to skills"
  ISSUES=$((ISSUES + 1))
elif [ "$IMSG_EXIT" != "0" ] && [ "$IMSG_EXIT" != "-" ]; then
  echo "WARN: imessage-sync failing (exit $IMSG_EXIT): likely Full Disk Access not granted to the venv interpreter"
  echo "  Fix: System Settings → Privacy & Security → Full Disk Access → add $HARNESS/imessage/.venv/bin/mist-imessage-python3 → toggle ON"
  echo "  (NOT /usr/bin/python3, an xcrun stub whose grant never applies; see imessage/README.md)"
  echo "  then: launchctl kickstart -k gui/\$(id -u)/com.exobrain.imessage-sync"
  ISSUES=$((ISSUES + 1))
elif [ ! -f "$IMSG_CACHE" ]; then
  echo "WARN: imessage cache snapshot missing -- sync has never succeeded (check FDA per imessage/README.md)"
  ISSUES=$((ISSUES + 1))
else
  IMSG_AGE=$(( ($(date +%s) - $(stat -f %m "$IMSG_CACHE")) / 3600 ))
  if [ "$IMSG_AGE" -gt 6 ]; then
    echo "WARN: imessage cache stale (${IMSG_AGE}h old; sync runs every 15m) -- check com.exobrain.imessage-sync"
    ISSUES=$((ISSUES + 1))
  else
    echo "OK: imessage-sync (cache ${IMSG_AGE}h fresh)"
  fi
fi

# TCC state (Full Disk Access + the carried user-database grants).
#
# READ THE REPORT FILE. NEVER PROBE TCC FROM HERE. This hook used to test FDA by
# listing ~/Library/Application Support/com.apple.TCC and then run mist-tcc-carry
# inline. Both read FDA-protected paths, and inside a hook the process TCC judges
# is the RESPONSIBLE one -- the claude CLI, which since 2.1.234 sits at
# auth_value=0, an explicit "Don't Allow". So each probe raised the "would like to
# access data from other apps" dialog: the very popup this subsystem exists to
# suppress, roughly five a day by 2026-08-21.
#
# Clicking Allow could never fix it. That dialog grants
# kTCCServiceSystemPolicyAppData, while TCC.db is gated on
# kTCCServiceSystemPolicyAllFiles, so the read still failed and the dialog came
# back next session. A button that cannot work is worse than no button.
#
# The launchd job (com.exobrain.tcc-carry-forward) has no such problem: launchd
# starts maintenance/venv/bin/mist-tcc-python3 directly, so that binary's OWN FDA
# grant applies, the read is silent, and it leaves the verdict in the report file.
# It fires on WatchPaths over the versions directory, so it has normally already
# run by the time a session starts; the kickstart below is only for a cold or
# stale report, and is deliberately fire-and-forget.
TCC_REPORT="$HARNESS/.claude/hooks/state/tcc-report"
TCC_JOB="com.exobrain.tcc-carry-forward"

# Resolve the live binary from the process ancestry (never pin the path -- the CLI
# has moved install locations before), falling back to whatever `claude` is on
# PATH. Reading ps and a symlink target touches nothing TCC protects.
CLAUDE_BIN=""
FDA_PID=$PPID
for _ in 1 2 3 4 5 6; do
  [ -z "$FDA_PID" ] && break
  [ "$FDA_PID" -le 1 ] 2>/dev/null && break
  FDA_COMM=$(ps -o comm= -p "$FDA_PID" 2>/dev/null)
  case "$FDA_COMM" in
    */claude|*/claude/versions/*) CLAUDE_BIN="$FDA_COMM"; break ;;
  esac
  FDA_PID=$(ps -o ppid= -p "$FDA_PID" 2>/dev/null | tr -d ' ')
done
[ -z "$CLAUDE_BIN" ] && CLAUDE_BIN=$(command -v claude 2>/dev/null)
[ -n "$CLAUDE_BIN" ] && CLAUDE_BIN=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$CLAUDE_BIN" 2>/dev/null)

# What a NEW session would launch, which is what the report describes. Distinct
# from CLAUDE_BIN above: this session may have started before the last upgrade,
# so the running binary and the one on PATH legitimately differ, and comparing
# the report against the running binary would call it stale forever.
CLAUDE_STABLE="$HOME/.local/share/claude/stable/claude"
CLAUDE_LINKED=$(command -v claude 2>/dev/null)
[ -n "$CLAUDE_LINKED" ] && CLAUDE_LINKED=$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$CLAUDE_LINKED" 2>/dev/null)

tcc_field() { sed -n "s/^$1=//p" "$TCC_REPORT" 2>/dev/null; }

TCC_STALE=""
if [ ! -f "$TCC_REPORT" ]; then
  TCC_STALE="no report yet"
else
  TCC_AGE=$(( ($(date +%s) - $(tcc_field generated_at 2>/dev/null || echo 0)) / 3600 ))
  TCC_SEEN=$(tcc_field claude_path)
  if [ "$TCC_AGE" -gt 12 ] 2>/dev/null; then
    TCC_STALE="report is ${TCC_AGE}h old"
  elif [ -n "$CLAUDE_LINKED" ] && [ "$TCC_SEEN" != "$CLAUDE_LINKED" ]; then
    TCC_STALE="report describes $TCC_SEEN, claude resolves to $CLAUDE_LINKED"
  fi
fi

if [ -n "$TCC_STALE" ]; then
  # Fire and forget. Waiting would buy nothing: this session's grants are already
  # fixed at exec time, so the fresh verdict is for the NEXT session to read.
  launchctl kickstart -k "gui/$(id -u)/$TCC_JOB" >/dev/null 2>&1
  echo "OK: TCC report refreshing in the background ($TCC_STALE)"
else
  # Which identity does TCC judge for THIS session? The Console is a real .app
  # with a stable bundle id, so its grant survives CLI upgrades; a bare-shell or
  # launchd session is judged by the versioned CLI path, which does not.
  # MIST_CONSOLE_SESSION is exported by the Console to every chat it spawns.
  if [ -n "$MIST_CONSOLE_SESSION" ]; then
    TCC_FDA=$(tcc_field console_fda)
    TCC_SUBJECT="the MIST Console app"
    TCC_FIX="System Settings -> Privacy & Security -> Full Disk Access -> /Applications/MIST Console.app -> toggle ON, then quit and reopen the Console"
  else
    TCC_FDA=$(tcc_field claude_fda)
    TCC_SUBJECT="the claude CLI"
    TCC_FIX="System Settings -> Privacy & Security -> Full Disk Access -> + -> Cmd-Shift-G -> $CLAUDE_STABLE -> toggle ON. Granted once, it holds across every release, so delete the leftover version-numbered rows while you are there."
  fi

  # Is the stable pin actually in effect? Full Disk Access is granted to
  # $CLAUDE_STABLE and to nothing else, so a `claude` that resolves anywhere
  # else is running without it -- which is how the popups start. The installer
  # rewriting the ~/.local/bin symlink back to a versioned path is the way this
  # breaks; com.exobrain.claude-stable-path normally repairs it within seconds.
  if [ -n "$CLAUDE_LINKED" ] && [ "$CLAUDE_LINKED" != "$CLAUDE_STABLE" ]; then
    echo "WARN: claude resolves to $CLAUDE_LINKED, not the FDA-granted stable path"
    echo "  Fix: maintenance/claude-stable-path.sh --now"
    ISSUES=$((ISSUES + 1))
  fi

  case "$TCC_FDA" in
    allowed)
      echo "OK: Full Disk Access held by $TCC_SUBJECT" ;;
    denied)
      # An explicit "Don't Allow", not merely unasked -- so this is not nagging
      # Alex toward a permission he declined, it is telling him why a dialog he
      # cannot dismiss keeps returning.
      echo "WARN: Full Disk Access is DENIED for $TCC_SUBJECT -- expect repeat \"access data from other apps\" popups that Allow cannot silence"
      echo "  Fix: $TCC_FIX"
      echo "  (TCC keys the bare CLI binary by path, so this recurs on every version bump)"
      ISSUES=$((ISSUES + 1)) ;;
    unset|"")
      # Used to stay quiet on the theory that Alex may not want the grant. That
      # theory died with the versioned paths: unset now means the ONE durable
      # grant was never made, and the dialogs it prevents come back per app-data
      # directory any routine touches.
      if [ -z "$MIST_CONSOLE_SESSION" ]; then
        echo "WARN: Full Disk Access has never been granted to $TCC_SUBJECT"
        echo "  Fix: $TCC_FIX"
        ISSUES=$((ISSUES + 1))
      fi ;;
    *)
      echo "WARN: Full Disk Access state for $TCC_SUBJECT reads '$TCC_FDA'"
      ISSUES=$((ISSUES + 1)) ;;
  esac

  # Surface a denied CLI even from a Console chat. Two reasons: every scheduled
  # routine runs under the bare CLI identity (the 21:00 and 23:00 popups on
  # 2026-08-20 were exactly that), and tccd's own AUTHREQ_ATTRIBUTION lines show
  # com.anthropic.claude-code as the responsible process inside Console sessions
  # too, so the Console's grant is not the blanket cover it looks like.
  CLI_FDA=$(tcc_field claude_fda)
  if [ -n "$MIST_CONSOLE_SESSION" ] && { [ "$CLI_FDA" = "denied" ] || [ "$CLI_FDA" = "unset" ]; }; then
    echo "WARN: Full Disk Access is $(if [ "$CLI_FDA" = denied ]; then echo DENIED; else echo UNGRANTED; fi) for the claude CLI -- scheduled routines will keep raising \"access data from other apps\" popups"
    echo "  Fix: System Settings -> Privacy & Security -> Full Disk Access -> + -> Cmd-Shift-G -> $CLAUDE_STABLE -> toggle ON (survives every release; delete the leftover version-numbered rows)"
    ISSUES=$((ISSUES + 1))
  fi

  TCC_PENDING=$(tcc_field user_grants_pending)
  if [ "${TCC_PENDING:-0}" -gt 0 ] 2>/dev/null; then
    echo "WARN: $TCC_PENDING TCC grant(s) not yet carried past the CLI upgrade"
    echo "  Fix: maintenance/bin/mist-tcc-carry"
    ISSUES=$((ISSUES + 1))
  fi
fi

# Scheduled MIST routines AND com.exobrain jobs -- check the LAST EXIT CODE, not
# just that the job is loaded. A loaded job that exits nonzero every fire (e.g.
# 78/EX_CONFIG when headless `claude` can't read the Keychain) is silently dead,
# and "loaded" alone hides that. launchctl list columns: PID  LAST_EXIT  LABEL.
# Flag any nonzero. imessage-sync is excluded: it has its own richer check above.
# $1 is the PID: a real PID means the job is running RIGHT NOW, so a nonzero
# last-exit is stale history from a previous run, not a current failure. That
# false-flagged the long-lived KeepAlive daemons (claude-bot showed a -15 from
# an earlier restart while happily connected to Discord for days). Periodic jobs
# are idle between fires with PID "-", so their real failures still surface.
ROUTINE_FAILS=$(launchctl list 2>/dev/null | awk '$3 ~ /^com\.(mist\.routine|exobrain)\./ && $3 != "com.exobrain.imessage-sync" && $1 == "-" && $2 != "-" && $2 != "0" {print $3" (exit "$2")"}')
if [ -n "$ROUTINE_FAILS" ]; then
  echo "WARN: scheduled routine(s) failing on last run -- investigate run-routine logs:"
  while IFS= read -r line; do
    echo "  FAIL: $line"
  done <<< "$ROUTINE_FAILS"
  ISSUES=$((ISSUES + 1))
fi

# Watcher health -- check for recent failures (last 24h). Suppress the WARN when
# processing has succeeded SINCE the failure: the 30-min poll self-recovers
# transient API errors, and a newer processing-log.json proves recovery.
for WATCHER in supernote plaud; do
  FAIL_LOG="$HOME/Library/Logs/exobrain/${WATCHER}-failures.log"
  if [ -f "$FAIL_LOG" ]; then
    FAIL_AGE=$(( ($(date +%s) - $(stat -f %m "$FAIL_LOG")) / 3600 ))
    if [ "$FAIL_AGE" -le 24 ]; then
      PROC_LOG="$HARNESS/processing-log.json"
      if [ -f "$PROC_LOG" ] && [ "$(stat -f %m "$PROC_LOG")" -gt "$(stat -f %m "$FAIL_LOG")" ]; then
        echo "OK: ${WATCHER}-watcher had a failure ${FAIL_AGE}h ago but processing succeeded since (recovered)"
      else
        LAST_FAIL=$(tail -2 "$FAIL_LOG")
        echo "WARN: ${WATCHER}-watcher has recent failures (${FAIL_AGE}h ago)"
        echo "  $LAST_FAIL"
        ISSUES=$((ISSUES + 1))
      fi
    fi
  fi
done

# Session-memory consolidator health -- the 23:00 job writes YYYY-MM-DD_DIGEST.md;
# if the newest digest is >26h old the consolidator is silently dead (observed
# 2026-07: three straight nights of failures behind exit 0) and startup context
# degrades fast. 26h allows for "today's digest doesn't exist until 23:00".
NEWEST_DIGEST=$(ls -t "$HOME/Exobrain/Claude/"*_DIGEST.md 2>/dev/null | head -1)
if [ -n "$NEWEST_DIGEST" ]; then
  DIGEST_AGE_H=$(( ($(date +%s) - $(stat -f %m "$NEWEST_DIGEST")) / 3600 ))
  if [ "$DIGEST_AGE_H" -gt 26 ]; then
    echo "WARN: session-memory digest stale (${DIGEST_AGE_H}h old; consolidator runs 23:00) -- check ~/Library/Logs/exobrain/session-memory-failures.log and session-memory-last.out"
    ISSUES=$((ISSUES + 1))
  fi
fi

# Processing log integrity
LOG="$HARNESS/processing-log.json"
if [ -f "$LOG" ]; then
  if python3 -c "import json; json.load(open('$LOG'))" 2>/dev/null; then
    TOTAL=$(python3 -c "import json; print(len(json.load(open('$LOG'))))" 2>/dev/null)
    echo "OK: Processing log ($TOTAL entries)"
  else
    echo "FAIL: Processing log -- corrupt JSON"
    ISSUES=$((ISSUES + 1))
  fi
else
  echo "FAIL: Processing log missing"
  ISSUES=$((ISSUES + 1))
fi

# Discord digest freshness -- read last_successful_fetch from JSON (file mtime
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
    # The job fires every 4h, so 24h of grace let three consecutive failures read
    # as OK -- on 2026-08-16 this printed 'OK ... 20h ago' for a digest that had
    # been dead since the previous afternoon. 12h is three missed cycles, which
    # still tolerates a normal overnight sleep gap (launchd does not fire while
    # the Mac is asleep, it catches up on wake).
    if age_h <= 12:
        print(f'OK: Discord digest (last successful fetch {age_h}h ago)')
    else:
        print(f'WARN: Discord digest stale ({age_h}h old; job runs every 4h) -- check com.exobrain.discord-digest and ~/Library/Logs/exobrain/discord-digest-failures.log')
except Exception as e:
    print(f'WARN: Discord digest unreadable -- {e}')
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
  echo "$ISSUES issue(s) detected -- check above."
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
      echo "(none yet -- first 11pm consolidator run will generate one)"
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
# (Dir name is Claude Code's per-project data dir: the project cwd with slashes
# replaced by dashes. A different clone path means a different dir name.)
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
