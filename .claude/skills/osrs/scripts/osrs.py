#!/usr/bin/env python3
"""
osrs.py - unified control toolkit for MIST's embodied OSRS (Alora) client.

Everything runs in the BACKGROUND (shared machine): eyes via per-window
screencapture (works occluded), input via the in-process Java agent socket
(mouse + keyboard, no focus stolen, system cursor untouched).

Usage:
  osrs.py win                 # window id + bounds (JSON)
  osrs.py shot [out.png]      # capture the client window to a PNG
  osrs.py send <agent cmd>    # raw command to the agent (ping/find/info/tree/state/npcs/...)
  osrs.py state               # player name + world coords (RuneLite reflection)
  osrs.py npcs                # on-screen NPCs: name@canvasX,canvasY
  osrs.py clicknpc <name>     # click the nearest on-screen NPC whose name contains <name>
  osrs.py click <x> <y>       # click canvas coords
  osrs.py type <text>         # type text into the focused game input
  osrs.py key  <ENTER|SPACE|BACKSPACE|TAB|ESC>
  osrs.py walkmap <dx> <dy>   # click the minimap offset from center (walk); +x east, +y south
  osrs.py launch              # launch the client + agent (background)
  osrs.py login               # full login -> in world (reads creds from gitignored file)

Canvas coords: the whole game (world view, minimap, inventory, chat) renders in
one 765x503 canvas. canvas = window - (0, TITLEBAR). The agent's click/state/npc
helpers already work in canvas space.
"""
import sys, os, socket, subprocess, time, json

AGENT = ("127.0.0.1", 43210)
OWNER = "RuneLite"
TITLE_SUBSTR = "Powered by RuneLite"           # main game window (not the bare 'Alora' child)
TITLEBAR = 32                                   # macOS title bar height (window->content offset)
JAVA = "/opt/homebrew/opt/openjdk@17/bin/java"
CLIENT_JAR = os.path.expanduser("~/alora/client_runelite.jar")
CLIENT_CWD = os.path.expanduser("~/alora")
AGENT_JAR = os.path.expanduser("~/Documents/osrs-companion/mist-agent/mist-agent.jar")
CREDS = os.path.expanduser("~/Documents/osrs-companion/credentials.json")
LOG = "/tmp/alora_agent.log"

def pid():
    try:
        return int(subprocess.check_output(["pgrep", "-f", "client_runelite.jar"]).split()[0])
    except Exception:
        return None

def window():
    from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID)
    p = pid()
    if p is None:
        return None
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID):
        if w.get('kCGWindowOwnerPID') == p and OWNER in str(w.get('kCGWindowOwnerName', '')) \
           and TITLE_SUBSTR in str(w.get('kCGWindowName', '')):
            b = w['kCGWindowBounds']
            return dict(wid=int(w['kCGWindowNumber']), x=int(b['X']), y=int(b['Y']),
                        w=int(b['Width']), h=int(b['Height']), name=str(w.get('kCGWindowName')))
    return None

def shot(out="/tmp/osrs.png"):
    win = window()
    if not win:
        return None
    subprocess.run(["screencapture", "-x", "-l%d" % win['wid'], out],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out if os.path.exists(out) else None

def send(cmd, timeout=5):
    try:
        s = socket.socket(); s.settimeout(timeout); s.connect(AGENT)
        s.sendall((cmd + "\n").encode())
        data = b""
        while True:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        s.close()
        return data.decode(errors="replace").strip()
    except Exception as e:
        return "SOCKET_ERR %s" % e

def launch():
    if pid():
        return "ALREADY_RUNNING pid=%d" % pid()
    env = dict(os.environ)
    cmd = [JAVA,
           "-javaagent:%s" % AGENT_JAR,
           "--add-exports", "java.desktop/com.apple.eawt=ALL-UNNAMED",
           "--add-opens", "java.desktop/com.apple.eawt=ALL-UNNAMED",
           "-XX:+DisableAttachMechanism", "-Xss2m", "-XX:CompileThreshold=1500", "-Xmx768m",
           "-jar", CLIENT_JAR]
    with open(LOG, "w") as f:
        subprocess.Popen(cmd, cwd=CLIENT_CWD, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)
    return "LAUNCHED"

def _wait_agent(deadline):
    while time.time() < deadline:
        if send("ping", 2) == "pong":
            return True
        time.sleep(1)
    return False

def _wait_gs(target, deadline):
    while time.time() < deadline:
        if send("gamestate") == target:
            return True
        time.sleep(1)
    return False

def login(account="mist"):
    """Full sequence: (relaunch if needed) -> equip screen -> credentials -> world.
    Robust: clicks the password field explicitly (relying on ENTER to switch fields
    is flaky on a cold client). Verifies via state() and retries the world-entry click.
    Canvas coords (765x503 fixed): equip-play (375,431); login username row auto-focuses
    so we type directly; password field (279,241); Login button (318,284); welcome
    'CLICK HERE TO PLAY' (382,310)."""
    creds = json.load(open(CREDS))["alora"][account]
    user, pw = creds["username"], creds["password"]
    if not pid():
        launch()
    if not _wait_agent(time.time() + 45):
        return "AGENT_TIMEOUT (client did not come up)"
    if "PLAYER name=" in send("state"):
        return "ALREADY_IN_WORLD " + send("state")
    # equip screen == gamestate STARTING; click 'CLICK HERE TO PLAY' until LOGIN_SCREEN
    _wait_gs("STARTING", time.time() + 30)
    t = time.time() + 30
    while send("gamestate") == "STARTING" and time.time() < t:
        send("click 375 431"); time.sleep(3)
    if not _wait_gs("LOGIN_SCREEN", time.time() + 15):
        return "NO_LOGIN_SCREEN gs=" + send("gamestate")
    # credentials. At LOGIN_SCREEN the username field is focused; 'Remember username' may
    # pre-fill it, so CLEAR first (else it doubles). ENTER advances username->password
    # (the native OSRS behaviour; reliable now that we gate on gamestate). The
    # username/password rows are too close to click-target separately.
    send("clear"); time.sleep(0.3)              # clear remembered/old username
    send("type %s" % user); time.sleep(0.4)
    send("key ENTER"); time.sleep(0.5)          # -> password field
    send("clear"); time.sleep(0.3)
    send("type %s" % pw); time.sleep(0.4)
    send("key ENTER"); time.sleep(3)            # submit login
    if not _wait_gs("LOGGED_IN", time.time() + 20):
        return "LOGIN_FAILED gs=" + send("gamestate") + " (bad creds?)"
    # gamestate==LOGGED_IN while the Alora 'WELCOME TO GIELINOR' overlay is still up and the
    # world isn't rendered (localToCanvas -> 0,0). Click 'CLICK HERE TO PLAY' until NPCs
    # report real (non 0,0) screen coords == world actually rendered.
    t = time.time() + 35
    while time.time() < t:
        send("click 382 310"); time.sleep(3)
        if _world_rendered():
            return "IN_WORLD " + send("state")
    return "STUCK_ON_WELCOME gs=" + send("gamestate")

def _world_rendered():
    """True once the 3D scene is live: at least one NPC resolves to a non-(0,0) canvas point."""
    npcs = send("npcs")
    return any('@' in c and '@0,0' not in c for c in npcs.split(';'))

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    c = a[0]
    if c == "win":
        print(json.dumps(window()))
    elif c == "shot":
        print(shot(a[1] if len(a) > 1 else "/tmp/osrs.png"))
    elif c == "launch":
        print(launch())
    elif c == "login":
        print(login(a[1] if len(a) > 1 else "mist"))
    elif c == "walkmap":
        # click minimap offset from its center. Minimap center ~ canvas (642, 84) for 765x503 fixed.
        cx, cy = 642, 84
        dx, dy = int(a[1]), int(a[2])
        print(send("click %d %d" % (cx + dx, cy + dy)))
    elif c in ("click", "type", "key", "clicknpc", "clickcomp"):
        print(send(c + " " + " ".join(a[1:])))
    elif c in ("state", "npcs", "find", "info", "tree", "ping"):
        print(send(c))
    else:
        print(send(" ".join(a)))

if __name__ == "__main__":
    main()
