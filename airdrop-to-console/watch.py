#!/usr/bin/env python3
"""AirDrop -> MIST Console watcher.

Fires (via launchd WatchPaths on ~/Downloads, plus an interval fallback) whenever
Downloads changes. Picks out ONLY images that arrived via AirDrop, moves them out
of Downloads into the Console's image dir, and injects each one into a MIST
Console chat so MIST can see it -- by default the one you have on screen, else a
dedicated pinned "iPhone Photos" chat. See resolve_target for the full order.

How we know a file is from AirDrop: macOS tags received files with the
com.apple.quarantine xattr, whose third ';'-separated field is the agent that put
it there. AirDrop's daemon is 'sharingd'; browser downloads read 'Chrome'/'Safari'.
The fourth field is a per-file UUID, which we use as a dedup key so a Downloads
change never re-posts the same photo.

Pure stdlib. macOS only (needs xattr + sips, both built in).
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
DOWNLOADS = os.path.join(HOME, "Downloads")
HARNESS = "/Users/alexhedtke/Documents/Exobrain harness"
ARCHIVE = os.path.join(HARNESS, "tmp", "images", "airdrop")
STATE_PATH = os.path.join(HARNESS, "airdrop-to-console", "state.json")
CONSOLE = "http://127.0.0.1:5014"
CHAT_TITLE = "\U0001F4F7 iPhone Photos"  # 📷
# How fresh the Console's "this chat is on screen" report has to be to count.
# The front-end re-reports every 30s, so anything older than a couple of missed
# beats means the Console isn't running and we fall back to recency.
ACTIVE_WINDOW = 90
# Recency fallback, used only when the Console can't say what's on screen (older
# build, or it's closed): if some chat saw activity within this many seconds, the
# photo joins it. Note this counts agent output, not attention, so it picks the
# wrong chat when a second chat is mid turn -- hence ACTIVE_WINDOW above.
RECENCY_WINDOW = 120

IMG_EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
# Extensions the Console/Read pipeline handles directly. Anything else (HEIC/HEIF)
# gets transcoded to JPEG first.
READABLE = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# ---------- state ----------

def load_state():
    try:
        with open(STATE_PATH) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("processed", [])   # list of quarantine UUIDs already handled
    s.setdefault("sid", None)       # dedicated Console chat id
    return s


def save_state(s):
    # cap the processed list so it can't grow without bound
    s["processed"] = s["processed"][-500:]
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, STATE_PATH)


# ---------- airdrop detection ----------

def quarantine_fields(path):
    """Return the ';'-split com.apple.quarantine value, or [] if absent."""
    try:
        out = subprocess.run(
            ["xattr", "-p", "com.apple.quarantine", path],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    return out.stdout.strip().split(";")


def airdrop_images():
    """Yield (path, uuid) for every AirDropped image currently in Downloads."""
    try:
        names = os.listdir(DOWNLOADS)
    except Exception:
        return
    for name in names:
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMG_EXTS:
            continue
        path = os.path.join(DOWNLOADS, name)
        if not os.path.isfile(path):
            continue
        fields = quarantine_fields(path)
        # fields: [flags, timestamp, agent, uuid]
        if len(fields) < 3 or fields[2] != "sharingd":
            continue
        uuid = fields[3] if len(fields) >= 4 else name
        yield path, uuid


# ---------- console api ----------

def _req(method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        CONSOLE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def console_up():
    try:
        _req("GET", "/sessions", timeout=4)
        return True
    except Exception:
        return False


def session_exists(sid):
    if not sid:
        return False
    try:
        _, lst = _req("GET", "/sessions", timeout=6)
    except Exception:
        return False
    return any(x.get("id") == sid for x in (lst or []))


def ensure_session(state):
    """Return the dedicated chat's sid, creating + titling + pinning it if needed."""
    if session_exists(state.get("sid")):
        return state["sid"]
    _, created = _req("POST", "/sessions", {})
    sid = created["id"]
    try:
        _req("POST", f"/sessions/{sid}/title", {"title": CHAT_TITLE})
        _req("POST", f"/sessions/{sid}/pin", {})   # toggles off->on
    except Exception:
        pass
    state["sid"] = sid
    save_state(state)
    return sid


def get_claim():
    """The live manual routing claim set via /here or /photos, or None."""
    try:
        _, c = _req("GET", "/airdrop-claim", timeout=6)
    except Exception:
        return None
    return c if c and c.get("target") else None


def focused_session_id(window=ACTIVE_WINDOW):
    """The chat currently on screen in the Console, if it's still reporting in."""
    try:
        _, a = _req("GET", "/active-chat", timeout=6)
    except Exception:
        return None          # older Console build without the endpoint
    if not a or not a.get("sid"):
        return None
    return a["sid"] if a.get("age", 1e9) <= window else None


def recent_session_id(window=RECENCY_WINDOW):
    """The most-recently-active chat, if it was active within `window` seconds."""
    try:
        _, lst = _req("GET", "/sessions", timeout=6)
    except Exception:
        return None
    now = time.time()
    best, best_ts = None, 0.0
    for s in (lst or []):
        la = s.get("last_activity") or 0
        if la > best_ts:
            best, best_ts = s.get("id"), la
    return best if best and (now - best_ts) <= window else None


def resolve_target(state):
    """Where should this photo land?
    Manual claim > the chat on screen > recency > dedicated chat."""
    claim = get_claim()
    if claim:
        tgt = claim["target"]
        if tgt == "dedicated":
            return ensure_session(state)
        if session_exists(tgt):
            return tgt
        # the claimed chat was deleted -> fall through to the rest
    fid = focused_session_id()
    if fid and session_exists(fid):
        return fid
    rid = recent_session_id()
    if rid:
        return rid
    return ensure_session(state)


def _post_image(sid, jpeg_path, ext, caption):
    """POST the image to one chat. Returns 'ok' | 'gone' | 'held' | 'fail'."""
    mime = "jpeg" if ext in (".jpg", ".jpeg") else ext.lstrip(".")
    with open(jpeg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {"text": caption, "image": f"data:image/{mime};base64,{b64}"}
    try:
        _, resp = _req("POST", f"/send/{sid}", payload)
    except urllib.error.HTTPError as e:
        if e.code == 404:                # chat was deleted mid-flight
            return "gone"
        raise
    if resp.get("held"):                 # context-cost gate
        return "held"
    return "ok" if resp.get("ok", False) else "fail"


def send_image(state, jpeg_path, ext, caption):
    """Deliver to the resolved target; on 404/held fall back to a fresh photos chat."""
    sid = resolve_target(state)
    status = _post_image(sid, jpeg_path, ext, caption)
    if status in ("gone", "held"):
        state["sid"] = None
        status = _post_image(ensure_session(state), jpeg_path, ext, caption)
    return status == "ok"


# ---------- move / transcode ----------

def stage_out_of_downloads(src, uuid):
    """Move src out of Downloads into ARCHIVE, transcoding HEIC->JPEG. Returns
    (final_path, final_ext) or (None, None) on failure."""
    os.makedirs(ARCHIVE, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    ext = ext.lower()
    tag = uuid[:8] if uuid else str(int(time.time()))
    if ext in READABLE:
        dst = os.path.join(ARCHIVE, f"{stem}-{tag}{ext}")
        try:
            os.replace(src, dst)
        except OSError:
            # cross-volume: copy then remove
            import shutil
            shutil.copy2(src, dst)
            os.remove(src)
        return dst, ext
    # HEIC/HEIF -> JPEG via sips, then drop the original from Downloads
    dst = os.path.join(ARCHIVE, f"{stem}-{tag}.jpg")
    r = subprocess.run(
        ["sips", "-s", "format", "jpeg", src, "--out", dst],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0 or not os.path.exists(dst):
        return None, None
    try:
        os.remove(src)
    except OSError:
        pass
    return dst, ".jpg"


# ---------- main ----------

def main():
    state = load_state()
    pending = [(p, u) for p, u in airdrop_images() if u not in state["processed"]]
    if not pending:
        return
    if not console_up():
        # Leave files in Downloads and don't mark them; we'll catch them on the
        # next Downloads change or interval tick once the Console is running.
        return

    processed_any = False
    for src, uuid in pending:
        final, ext = stage_out_of_downloads(src, uuid)
        if not final:
            continue
        caption = "\U0001F4F7 AirDropped from iPhone"
        try:
            ok = send_image(state, final, ext, caption)
        except Exception as e:
            print(f"send failed for {os.path.basename(final)}: {e}", file=sys.stderr)
            ok = False
        if ok:
            state["processed"].append(uuid)
            processed_any = True
            print(f"routed {os.path.basename(final)} -> Console")

    if processed_any:
        save_state(state)


if __name__ == "__main__":
    main()
