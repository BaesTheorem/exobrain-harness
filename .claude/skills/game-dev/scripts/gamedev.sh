#!/bin/bash
# Game-dev tool bootstrap: brings up the MCP host apps so their servers are reachable.
# Usage: gamedev.sh {start|status|stop} [godot|blender|all] [project-path]
#
# Both MCP servers are hosted BY their app -- no app, no tools. Every action here
# is idempotent: ports are checked before anything launches, so re-running is safe.

set -uo pipefail

GODOT_HTTP=8000    # godot-ai MCP endpoint
GODOT_WS=9500      # godot-ai -> editor websocket
BLENDER_SOCK=9876  # blender-mcp addon socket

export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"  # Finder/launchd give a bare PATH; uv lives in ~/.local/bin

BLENDER_BIN="/Applications/Blender.app/Contents/MacOS/Blender"
LOG_DIR="$HOME/Library/Logs/exobrain"
mkdir -p "$LOG_DIR"

port_open() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# The homebrew binary registers as `godot` (lowercase) while /Applications/Godot.app
# registers as `Godot`. `pgrep -x Godot` silently matches NEITHER on a homebrew launch
# and returns "not running" for a live editor, so always match case-insensitively.
godot_running() { pgrep -ix godot >/dev/null 2>&1; }
blender_running() { pgrep -ix blender >/dev/null 2>&1; }

wait_for_port() {  # port, seconds
  local p=$1 limit=${2:-60} i=0
  while [ $i -lt "$limit" ]; do
    port_open "$p" && return 0
    sleep 1; i=$((i+1))
  done
  return 1
}

# Wait for the Godot EDITOR, not just the port. Two reasons this must poll the
# process: a stale orphaned server already holds the port (so a port wait returns
# instantly and reports a false READY), and returning early lets this script exit
# while the editor is still initializing, which takes the editor down with it.
wait_for_editor() {
  local limit=${1:-90} i=0
  while [ $i -lt "$limit" ]; do
    if godot_running && port_open "$GODOT_HTTP"; then
      sleep 3   # let the websocket session attach before declaring victory
      return 0
    fi
    sleep 1; i=$((i+1))
  done
  return 1
}

# Locate a Godot project: walk up first, then look one level down. The second pass
# matters because repos commonly keep the project in a subdir (myrepo/game/).
find_godot_project() {
  local start d
  start="$(cd "${1:-$PWD}" 2>/dev/null && pwd)" || return 1

  d="$start"
  while [ "$d" != "/" ]; do
    [ -f "$d/project.godot" ] && { echo "$d"; return 0; }
    d="$(dirname "$d")"
  done

  local sub
  for sub in "$start"/*/; do
    [ -f "$sub/project.godot" ] && { echo "${sub%/}"; return 0; }
  done
  return 1
}

start_godot() {
  local proj="${1:-}"
  # The Python server outlives a force-quit editor and keeps holding both ports,
  # so an open port alone does NOT mean an editor is attached. Require the editor
  # process too, otherwise we would skip launching and hand back a headless server.
  if port_open "$GODOT_HTTP" && godot_running; then
    echo "godot-ai: already up on :$GODOT_HTTP with an editor attached"
    return 0
  fi
  if port_open "$GODOT_HTTP"; then
    echo "godot-ai: stale server on :$GODOT_HTTP with no editor -- launching editor to re-attach"
  fi
  if [ -z "$proj" ]; then
    proj="$(find_godot_project "$PWD")" || {
      echo "godot-ai: SKIP -- no project.godot found at or above $PWD (pass a path explicitly)"
      return 1
    }
  fi
  [ -f "$proj/project.godot" ] || { echo "godot-ai: FAIL -- no project.godot in $proj"; return 1; }

  if ! grep -q "godot_ai/plugin.cfg" "$proj/project.godot" 2>/dev/null; then
    echo "godot-ai: WARN -- plugin not enabled in $(basename "$proj")/project.godot."
    echo "          Copy addons/godot_ai in and add it to [editor_plugins] enabled=..."
  fi

  # macOS App Nap parks occluded Godot windows in the AppKit event loop (2% CPU zombie).
  defaults write org.godotengine.godot NSAppSleepDisabled -bool YES 2>/dev/null

  echo "godot-ai: launching editor for $(basename "$proj")..."
  nohup godot --path "$proj" --editor > "$LOG_DIR/gamedev-godot.log" 2>&1 &
  disown 2>/dev/null || true

  if wait_for_editor 90; then
    echo "godot-ai: READY on :$GODOT_HTTP (ws :$GODOT_WS) -- 43 tools, editor attached"
  else
    echo "godot-ai: FAIL -- editor never came up. Check $LOG_DIR/gamedev-godot.log"
    echo "          Most common cause: uv not on PATH, or the plugin is disabled."
    return 1
  fi
}

start_blender() {
  if port_open "$BLENDER_SOCK"; then
    echo "blender-mcp: already up on :$BLENDER_SOCK"
    return 0
  fi
  [ -x "$BLENDER_BIN" ] || { echo "blender-mcp: SKIP -- Blender not installed"; return 1; }

  # Blender open but socket closed: a second instance would fight over prefs. Hand it back to the user.
  if blender_running; then
    echo "blender-mcp: Blender is running but the socket is closed."
    echo "             Click View3D sidebar (N) > BlenderMCP > Connect to Claude."
    return 1
  fi

  echo "blender-mcp: launching Blender..."
  # The operator needs a real context, so defer it past startup with a timer.
  nohup "$BLENDER_BIN" --python-expr "
import bpy
def _start():
    try:
        bpy.ops.blendermcp.start_server()
        print('BLENDERMCP_STARTED')
    except Exception as e:
        print('BLENDERMCP_FAIL:', e)
    return None
bpy.app.timers.register(_start, first_interval=3.0)
" > "$LOG_DIR/gamedev-blender.log" 2>&1 &

  if wait_for_port "$BLENDER_SOCK" 90; then
    echo "blender-mcp: READY on :$BLENDER_SOCK -- 22 tools"
  else
    echo "blender-mcp: FAIL -- :$BLENDER_SOCK never opened. Check $LOG_DIR/gamedev-blender.log"
    return 1
  fi
}

cmd_status() {
  echo "== game-dev tools =="
  # Readiness = server listening AND an editor process attached. The server alone
  # is a stale orphan that answers MCP but drives nothing.
  if port_open "$GODOT_HTTP" && godot_running; then
    echo "  godot-ai     UP    :$GODOT_HTTP (editor attached)"
  elif port_open "$GODOT_HTTP"; then
    echo "  godot-ai     STALE :$GODOT_HTTP server orphaned, no editor -- 'start godot' re-attaches"
  else
    echo "  godot-ai     down  (open the Godot editor)"
  fi
  if port_open "$BLENDER_SOCK"; then
    echo "  blender-mcp  UP    :$BLENDER_SOCK"
  elif blender_running; then
    echo "  blender-mcp  down  (Blender open, socket closed -- N sidebar > BlenderMCP > Connect)"
  else
    echo "  blender-mcp  down  (Blender not running)"
  fi
  local p
  p="$(find_godot_project "$PWD" 2>/dev/null)" && echo "  godot project: $p"
  echo
  echo "  Asset generators (no daemon, run on demand):"
  for t in mist-image mist-music; do
    local b="$HOME/Documents/Exobrain harness/$t/bin/$t"
    [ -x "$b" ] && echo "    $t   ok" || echo "    $t   missing"
  done
}

cmd_stop() {  # no ;;& fallthrough here -- macOS ships bash 3.2
  local what="${1:-all}"
  if [ "$what" = "godot" ] || [ "$what" = "all" ]; then
    pkill -ix godot 2>/dev/null && echo "godot: stopped" || echo "godot: not running"
  fi
  if [ "$what" = "blender" ] || [ "$what" = "all" ]; then
    pkill -ix blender 2>/dev/null && echo "blender: stopped" || echo "blender: not running"
  fi
}

ACTION="${1:-status}"
TARGET="${2:-all}"
PROJECT="${3:-}"

case "$ACTION" in
  start)
    case "$TARGET" in
      godot)   start_godot "$PROJECT" ;;
      blender) start_blender ;;
      all)     start_godot "$PROJECT"; start_blender ;;
      *) echo "unknown target: $TARGET"; exit 2 ;;
    esac
    echo; cmd_status
    ;;
  status) cmd_status ;;
  stop)   cmd_stop "$TARGET" ;;
  *) echo "usage: gamedev.sh {start|status|stop} [godot|blender|all] [project-path]"; exit 2 ;;
esac
