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
# Main game window title: Alora = "Alora - <char> - Powered by RuneLite"; official = "RuneLite"
# (or "RuneLite - <char>"). Both contain "RuneLite"; aux windows (splash/menubar) have empty
# titles, so we match owner=RuneLite + non-empty title + largest area.
TITLE_SUBSTR = "RuneLite"
TITLEBAR = 32                                   # macOS title bar height (window->content offset)
JAVA = "/opt/homebrew/opt/openjdk@17/bin/java"
CLIENT_JAR = os.path.expanduser("~/alora/client_runelite.jar")
CLIENT_CWD = os.path.expanduser("~/alora")
AGENT_JAR = os.path.expanduser("~/Documents/osrs-companion/mist-agent/mist-agent.jar")
CREDS = os.path.expanduser("~/Documents/osrs-companion/credentials.json")
LOG = "/tmp/alora_agent.log"

def pid():
    # Alora client = client_runelite.jar; official RuneLite = net.runelite.client.RuneLite
    for pat in ("client_runelite.jar", "net.runelite.client.RuneLite"):
        try:
            out = subprocess.check_output(["pgrep", "-f", pat]).split()
            if out:
                return int(out[0])
        except Exception:
            continue
    return None

def window():
    from Quartz import (CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID)
    p = pid()
    if p is None:
        return None
    best = None
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID):
        name = str(w.get('kCGWindowName') or '')
        if w.get('kCGWindowOwnerPID') == p and OWNER in str(w.get('kCGWindowOwnerName', '')) \
           and TITLE_SUBSTR in name:
            b = w['kCGWindowBounds']
            area = int(b['Width']) * int(b['Height'])
            cand = dict(wid=int(w['kCGWindowNumber']), x=int(b['X']), y=int(b['Y']),
                        w=int(b['Width']), h=int(b['Height']), name=name, _area=area)
            if best is None or area > best['_area']:    # main game window = largest titled one
                best = cand
    if best:
        best.pop('_area', None)
    return best

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

RL_REPO = os.path.expanduser("~/.runelite/repository2")   # official RuneLite client jars
LOG_VANILLA = "/tmp/runelite_agent.log"

RL_CREDS = os.path.expanduser("~/.runelite/credentials.properties")  # JX_* tokens persisted by RuneLite

def read_jx_creds():
    """Read Jagex-account tokens from ~/.runelite/credentials.properties (Java .properties
    format, plaintext) that RuneLite writes when launched via the Jagex Launcher with
    --insecure-write-credentials. Returns {JX_ACCESS_TOKEN: ..., ...}. The RuneLite client
    reads these from the ENV, so launch_vanilla merges them into the child JVM's environment;
    this is what lets MISTci's agent-injected client authenticate without the Jagex Launcher.
    Any key starting with JX_ is passed through verbatim (key-agnostic on purpose)."""
    creds = {}
    if not os.path.exists(RL_CREDS):
        return creds
    with open(RL_CREDS) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            # Only pass through non-empty JX_* values. The Jagex Launcher hands RuneLite the
            # game session (JX_SESSION_ID + JX_CHARACTER_ID) but often leaves ACCESS/REFRESH
            # empty; an empty env var reads as "present but invalid" and can break login, so skip.
            if k.startswith("JX_") and v:
                creds[k] = v
    return creds

def sanitize_jx_creds():
    """RuneLite's injected-client reads credentials.properties DIRECTLY from disk. The Jagex
    Launcher on macOS mints only JX_SESSION_ID + JX_CHARACTER_ID (the game session, which is
    all that's required and does not expire) and writes JX_ACCESS_TOKEN / JX_REFRESH_TOKEN /
    JX_DISPLAY_NAME EMPTY. An empty JX_ACCESS_TOKEN reads as 'present but invalid' and drops
    the client to the legacy login screen instead of Jagex auto-login. Fix: rewrite the file
    keeping only non-empty JX_* lines. Idempotent; runs before every launch so a fresh re-mint
    self-heals. Validated live 2026-07-15: 2-key file -> LOGGED_IN. Backs up the raw file once."""
    if not os.path.exists(RL_CREDS):
        return
    kept = read_jx_creds()  # already drops empties
    with open(RL_CREDS) as f:
        raw = f.read()
    # only rewrite if the file actually carries empty JX_ lines
    has_empty = any(l.strip().startswith("JX_") and l.strip().endswith("=") for l in raw.splitlines())
    if not has_empty or not kept:
        return
    bak = RL_CREDS + ".raw"
    if not os.path.exists(bak):
        with open(bak, "w") as f:
            f.write(raw)
    with open(RL_CREDS, "w") as f:
        f.write("#Do not share this file with anyone\n")
        for k, v in kept.items():
            f.write("%s=%s\n" % (k, v))

def launch_vanilla():
    """Launch the OFFICIAL RuneLite client (vanilla OSRS) with the mist-agent injected.
    Validated 2026-06-20: -javaagent loads despite DisableAttachMechanism, reflection +
    eyes + hands all work on the official client. Populate ~/.runelite/repository2 first by
    running the RuneLite launcher once. Jagex-account login needs JX_* tokens in the env:
    we source them from ~/.runelite/credentials.properties (minted once via the Jagex
    Launcher + --insecure-write-credentials), falling back to any JX_* already in os.environ.
    Without them you land on the login screen."""
    if pid():
        return "ALREADY_RUNNING pid=%d" % pid()
    import glob
    cp = ":".join(sorted(glob.glob(os.path.join(RL_REPO, "*.jar"))))
    if not cp:
        return "NO_RUNELITE_CLIENT: run the RuneLite launcher once to populate %s" % RL_REPO
    sanitize_jx_creds()  # strip empty JX_* lines so the client uses the session instead of the login screen
    env = dict(os.environ)
    jx = read_jx_creds()
    env.update(jx)  # credentials.properties wins over stale shell env
    cmd = [JAVA, "-javaagent:%s" % AGENT_JAR, "-cp", cp,
           "-XX:+DisableAttachMechanism", "-Xmx768m", "-Xss2m", "-XX:CompileThreshold=1500",
           "--add-opens=java.base/java.net=ALL-UNNAMED",
           "--add-opens=java.base/java.io=ALL-UNNAMED",
           "--add-opens=java.desktop/com.apple.eawt=ALL-UNNAMED",
           "-Dsun.java2d.metal=false", "-Dsun.java2d.opengl=true",
           "-Dapple.awt.application.appearance=system",
           "-Drunelite.launcher.version=2.7.7",
           "net.runelite.client.RuneLite"]
    with open(LOG_VANILLA, "w") as f:
        subprocess.Popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    has_tok = bool(env.get("JX_ACCESS_TOKEN"))
    src = "credentials.properties" if jx.get("JX_ACCESS_TOKEN") else ("shell env" if has_tok else "none")
    return "LAUNCHED_VANILLA (JX_* token source: %s -> %s)" % (src, "authenticated" if has_tok else "login screen")

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

# ---------------------------------------------------------------------------
# Combat: autonomous training + bodyguard loops (see SKILL.md "Combat")
# ---------------------------------------------------------------------------

def server_cmd(text):
    """Send an Alora ::-command (or any chat line). Chat input goes straight to the
    game when no dialog is focused, so: clear, type, ENTER."""
    send("clear"); time.sleep(0.2)
    send("type %s" % text); time.sleep(0.3)
    send("key ENTER"); time.sleep(0.3)
    return "SENT " + text

def _hp():
    """(current, max) HP, or (None, None) if not readable."""
    r = send("hp")
    try:
        _, cur, mx = r.split()
        return int(cur), int(mx)
    except Exception:
        return None, None

def _in_combat():
    return send("target").startswith("TARGET")

def _parse_at(chunk):
    """'Name@cx,cy' -> ('Name', x, y) or None (skips @off / @0,0)."""
    chunk = chunk.strip()
    if '@' not in chunk or '@off' in chunk or '@0,0' in chunk:
        return None
    name, xy = chunk.rsplit('@', 1)
    try:
        x, y = (int(v) for v in xy.split(','))
        return name, x, y
    except Exception:
        return None

# canvas center of the world view (for "nearest to me" sorting)
WORLD_CX, WORLD_CY = 250, 167

def attack_nearest(prefer):
    """Click the best on-screen NPC: prefer names matching the priority tokens, then
    nearest to the player. Left-click default op on a combat NPC is Attack."""
    entries = []
    for chunk in send("npcs").split(';'):
        e = _parse_at(chunk)
        if e:
            entries.append(e)
    if not entries:
        return "NO_NPCS_ONSCREEN"
    def score(nm):
        low = nm.lower()
        for i, t in enumerate(prefer):
            if t.lower() in low:
                return i
        return len(prefer)
    entries.sort(key=lambda e: (score(e[0]), abs(e[1] - WORLD_CX) + abs(e[2] - WORLD_CY)))
    nm, x, y = entries[0]
    send("click %d %d" % (x, y))
    return "ATTACK %s @%d,%d" % (nm, x, y)

def reset_tolerance(dist=64):
    """Crabs/aggressives go tolerant after ~10 min. Walk out of the tolerance region
    (roughly a minimap radius) and back to re-trigger aggression."""
    send("click %d %d" % (642 + dist, 84)); time.sleep(9)   # run away (east on minimap)
    send("click %d %d" % (642 - dist, 84)); time.sleep(9)   # run back
    return "RESET_TOLERANCE"

# priority targets for generic combat training (Alora ::train = crabs)
TRAIN_TARGETS = ["Crab", "Rock", "Sand", "Ammonite", "Sea snake", "Experiment",
                 "Giant", "Warrior", "Guard", "Goblin", "Cow", "Chicken", "rat", "Man", "Woman"]

INVENTORY_TAB_ICON = (629, 168)         # fixed-mode inventory tab (top row, 4th icon)

def _open_inventory():
    """Inventory-slot clicks only land when the inventory tab is the active side panel."""
    send("click %d %d" % INVENTORY_TAB_ICON); time.sleep(0.4)

def _slot_xy(i):
    return (563 + 42 * (i % 4), 213 + 36 * (i // 4))

def _att_level():
    for tok in send("stats").split():
        if tok.startswith("ATT="):
            try:
                return int(tok.split('=')[1].split('/')[0])
            except Exception:
                return None
    return None

def eat_food():
    """Eat the first food in the pack (opens the inventory tab; agent eat() relies on a
    widget Alora's old client doesn't expose, so we click the slot by canvas coords)."""
    _open_inventory()
    for chunk in send("inv").split(';'):
        parts = chunk.strip().split(':', 2)
        if len(parts) == 3 and any(f in parts[2].lower() for f in
                                   ("lobster", "shark", "swordfish", "tuna", "salmon", "monkfish",
                                    "trout", "bass", "anglerfish", "karambwan", "manta")):
            x, y = _slot_xy(int(parts[0]))
            send("click %d %d" % (x, y))
            return "ATE " + parts[2]
    return "NO_FOOD"

def _wield_best_weapon(style_after=3):
    """At 40 Attack, swap the iron scimitar for the rune scimitar if it's still in the pack.
    Equipping a weapon RESETS the attack style to default, so re-assert style afterward."""
    if (_att_level() or 0) < 40:
        return False
    _open_inventory()
    for chunk in send("inv").split(';'):
        parts = chunk.strip().split(':', 2)
        if len(parts) == 3 and 'rune_scimitar' in parts[2].lower():
            x, y = _slot_xy(int(parts[0]))
            send("click %d %d" % (x, y)); time.sleep(0.5)
            setstyle(style_after)            # weapon swap reset the style -> restore it
            _open_inventory()                # leave inventory tab active for eating
            return True
    return False

def train(minutes=30, goto="::train", food_pct=0.5, style=3):
    """Autonomous melee training loop. Idempotently logs in, teleports to the training
    spot (Alora ::train -> rock crabs), sets the attack style, then keeps a target engaged,
    eats when low, swaps to the best weapon at 40 Attack, and re-wakes crabs when nothing is
    attacking. Auto-retaliate does the per-hit work. style: 0 acc 1 aggr 2 def 3 controlled."""
    if "PLAYER name=" not in send("state"):
        r = login()
        if "IN_WORLD" not in r and "ALREADY_IN_WORLD" not in r:
            return "NOT_IN_WORLD: " + r
    if goto:
        server_cmd(goto); time.sleep(6)
    setstyle(style); time.sleep(0.4)
    _open_inventory()                        # keep inventory tab active so eat/swap clicks land
    start = time.time()
    deadline = start + minutes * 60
    last_reset = time.time()
    last_click = time.time()
    last_upgrade_check = 0
    s0 = send("stats")
    idle_rounds = 0
    while time.time() < deadline:
        send("key SPACE")                    # dismiss any level-up "click to continue" dialog
        cur, mx = _hp()
        if cur is not None and mx and cur <= max(8, int(mx * food_pct)):
            eat_food()                       # opens inv tab + clicks food; no-op if none
        if time.time() - last_upgrade_check > 30:
            _wield_best_weapon(style); last_upgrade_check = time.time()
        if not _in_combat():
            attack_nearest(TRAIN_TARGETS)    # clicking a dormant "Rocks" walks into it = wakes the crab
            last_click = time.time()
            time.sleep(2.5)
            if not _in_combat():
                idle_rounds += 1
                # nothing aggroing: either out of range or tolerant -> reset every few idles
                if idle_rounds >= 2 and time.time() - last_reset > 45:
                    reset_tolerance(); last_reset = time.time(); idle_rounds = 0
            else:
                idle_rounds = 0
        else:
            idle_rounds = 0
            time.sleep(5)
        if time.time() - last_click > 14 * 60:   # anti-idle: stay under the 20-min logout
            send("click 642 84"); last_click = time.time()
    return "TRAIN_DONE %dmin | before: %s | after: %s" % (minutes, s0, send("stats"))

# Common OSRS pets follow their owner and read as "interacting with" them, so threats()
# surfaces them too. Never attack a pet. (Not exhaustive -- covers the common skilling/boss pets.)
PETS = {"phoenix", "heron", "rocky", "beaver", "tangleroot", "baby mole", "rift guardian",
        "giant squirrel", "rock golem", "chompy chick", "vorki", "olmlet", "tzrek-jad",
        "jal-nib-rek", "abyssal orphan", "hellpuppy", "skotos", "smolcano", "youngllef",
        "bloodhound", "herbi", "baby mimic", "wisp", "pet", "cat", "kitten", "lil' zik",
        "nexling", "muphin", "butch", "lil'viathan", "baron", "scurry", "smol heredit"}

def _is_pet(name):
    n = name.strip().lower()
    return any(p in n for p in PETS)

def guard(ward, minutes=30, food_pct=0.5):
    """Bodyguard loop. OSRS has no taunt: once an NPC locks onto <ward> it cannot be
    pulled off, so MIST's job is to KILL threats fast (and damage-share in multi-combat)
    while following <ward>. She also eats to stay alive. Honest about its limits."""
    if "PLAYER name=" not in send("state"):
        return "NOT_IN_WORLD (login first)"
    deadline = time.time() + minutes * 60
    kills = 0
    while time.time() < deadline:
        cur, mx = _hp()
        if cur is not None and mx and cur <= max(10, int(mx * food_pct)):
            send("eat")
        engaged = False
        th = send("threats %s" % ward)
        if th and th not in ("NO_THREATS",) and not th.startswith("THREATS_ERR"):
            for chunk in th.split(';'):
                chunk = chunk.strip()
                if '->' not in chunk or '@' not in chunk or '@off' in chunk:
                    continue
                npc_name = chunk.split('->', 1)[0]
                if _is_pet(npc_name):          # don't attack someone's pet
                    continue
                _, xy = chunk.rsplit('@', 1)
                try:
                    x, y = (int(v) for v in xy.split(','))
                except Exception:
                    continue
                send("click %d %d" % (x, y))   # attack the NPC attacking the ward
                engaged = True
                kills += 1
                break
        if not engaged and not _in_combat():
            for chunk in send("players").split(';'):
                e = _parse_at(chunk)
                if e and ward.lower() in e[0].lower():
                    send("click %d %d" % (e[1], e[2]))   # left-click player = Follow
                    break
        time.sleep(3)
    return "GUARD_DONE %dmin watching '%s' | engagements~%d | %s" % (minutes, ward, kills, send("stats"))

# Combat attack-style tab (fixed mode, calibrated live on Alora). The combat-options
# widget is group 593; its four style buttons are static children s3-s6 (71x47).
# Mapping is by FUNCTION, not screen position, so it holds across weapon types:
#   0 accurate(+Attack)  1 aggressive(+Strength)  2 defensive(+Defence)  3 controlled(all)
# Button centers for a scimitar-class weapon: Chop=s3, Slash=s4, Lunge=s5, Block=s6.
COMBAT_TAB_ICON = (530, 168)            # fixed-mode combat tab toggle
STYLE_XY = {0: (602, 272),             # Chop  -> Accurate (Attack)
            1: (681, 272),             # Slash -> Aggressive (Strength)
            2: (681, 326),             # Block -> Defensive (Defence)
            3: (602, 326)}             # Lunge -> Controlled (all three)
STYLE_NAME = {0: "accurate/Attack", 1: "aggressive/Strength", 2: "defensive/Defence", 3: "controlled/all"}

def _combat_tab_open():
    """True if the style buttons are on-screen (combat tab is the active side panel).
    A hidden widget RETAINS its last canvas coords, so coords alone give a false positive
    once the tab has ever been shown -- must check the HID flag on the s3 entry."""
    dump = send("widgetkids 593 0")
    i = dump.find("s3[")
    if i < 0:
        return False
    entry = dump[i:dump.find("]", i)]
    return "HID" not in entry and "-1,-1" not in entry

def setstyle(idx):
    """Switch attack style. Always opens the combat tab first (idempotent on Alora -- clicking
    an already-open tab keeps it open), verifies it's open, then clicks the style button.
    0 accurate(Att) 1 aggressive(Str) 2 defensive(Def) 3 controlled(all)."""
    idx = int(idx)
    if idx not in STYLE_XY:
        return "BAD_STYLE %s (use 0-3)" % idx
    for _ in range(3):                       # post-teleport the panel can lag; retry until open
        if _combat_tab_open():
            break
        send("click %d %d" % COMBAT_TAB_ICON); time.sleep(0.6)
    x, y = STYLE_XY[idx]
    send("click %d %d" % (x, y))
    return "STYLE %d (%s)" % (idx, STYLE_NAME[idx])

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
    elif c == "launch-vanilla":
        print(launch_vanilla())
    elif c == "login":
        print(login(a[1] if len(a) > 1 else "mist"))
    elif c == "walkmap":
        # click minimap offset from its center. Minimap center ~ canvas (642, 84) for 765x503 fixed.
        cx, cy = 642, 84
        dx, dy = int(a[1]), int(a[2])
        print(send("click %d %d" % (cx + dx, cy + dy)))
    elif c in ("click", "type", "key", "clicknpc", "clickcomp"):
        print(send(c + " " + " ".join(a[1:])))
    elif c in ("state", "npcs", "find", "info", "tree", "ping",
               "stats", "hp", "inv", "players", "target", "threats"):
        print(send(c + ("" if len(a) == 1 else " " + " ".join(a[1:]))))
    elif c == "eat":                       # canvas-slot eat (Alora has no inventory widget)
        print(eat_food())
    elif c == "cmd":                       # Alora ::command or chat line
        print(server_cmd(" ".join(a[1:])))
    elif c == "attack":                    # attack nearest matching NPC (by name tokens)
        print(attack_nearest(a[1:] if len(a) > 1 else TRAIN_TARGETS))
    elif c == "reset":                     # walk out + back to reset aggression
        print(reset_tolerance(int(a[1]) if len(a) > 1 else 64))
    elif c == "setstyle":
        print(setstyle(a[1] if len(a) > 1 else 3))
    elif c == "train":                     # train [minutes] [goto-cmd] [style 0-3]
        print(train(int(a[1]) if len(a) > 1 else 30,
                    a[2] if len(a) > 2 else "::train",
                    style=int(a[3]) if len(a) > 3 else 3))
    elif c == "guard":                     # guard <wardName> [minutes]
        if len(a) < 2:
            print("usage: guard <wardName> [minutes]"); return
        print(guard(a[1], int(a[2]) if len(a) > 2 else 30))
    else:
        print(send(" ".join(a)))

if __name__ == "__main__":
    main()
