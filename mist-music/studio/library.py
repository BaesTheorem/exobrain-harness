"""Songs and uploads on disk. One folder per song, JSON sidecar, no database.

  library/<id>/song.mp3        the take
  library/<id>/meta.json       everything about it (request, seed, lyrics, LRC...)
  library/<id>/cover.png       optional art
  library/<id>/stems/*.mp3     optional separated stems
  uploads/<id>.<ext>           a track Alex brought in (cover / repaint source)
  uploads/<id>.json            its sidecar

Portable on purpose: the chat side of MIST can read the same folders.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid

from .config import LIBRARY_DIR, UPLOADS_DIR
from .engine import probe_duration

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aiff", ".aif", ".aac"}
_lock = threading.Lock()


def _new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _safe_name(s: str, fallback: str = "song") -> str:
    s = re.sub(r"[^\w\s.-]", "", s or "").strip().replace(" ", "-")
    return s[:80] or fallback


def _write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# -- songs ------------------------------------------------------------------

def song_dir(song_id: str) -> str:
    if not re.fullmatch(r"[\w-]+", song_id or ""):
        raise ValueError("bad song id")
    return os.path.join(LIBRARY_DIR, song_id)


def derive_title(meta: dict) -> str:
    if meta.get("title"):
        return meta["title"]
    for line in (meta.get("lyrics") or "").splitlines():
        line = line.strip()
        if line and not line.startswith("["):
            return line[:60]
    cap = (meta.get("caption") or "").split(",")[0].strip()
    if cap:
        return cap[:60].title()
    if meta.get("description"):
        return meta["description"][:60]
    return "Untitled"


def add_song(audio_path: str, meta: dict) -> dict:
    """Copy a generated take into the library and write its sidecar."""
    song_id = _new_id()
    d = song_dir(song_id)
    os.makedirs(d, exist_ok=True)
    ext = os.path.splitext(audio_path)[1].lower() or ".mp3"
    dst = os.path.join(d, "song" + ext)
    shutil.copy2(audio_path, dst)
    meta = dict(meta)
    meta.update({
        "id": song_id, "file": os.path.basename(dst), "created": time.time(),
        "duration": probe_duration(dst), "favorite": False, "art": False, "stems": {},
        "tags": meta.get("tags") or [],
    })
    meta["title"] = derive_title(meta)
    _write_json(os.path.join(d, "meta.json"), meta)
    return meta


def get_song(song_id: str) -> dict | None:
    try:
        d = song_dir(song_id)
    except ValueError:
        return None
    meta = _read_json(os.path.join(d, "meta.json"))
    if not meta:
        return None
    meta["art"] = os.path.isfile(os.path.join(d, "cover.png"))
    stems_dir = os.path.join(d, "stems")
    if os.path.isdir(stems_dir):
        meta["stems"] = {os.path.splitext(f)[0]: f for f in sorted(os.listdir(stems_dir))
                         if os.path.splitext(f)[1].lower() in AUDIO_EXTS}
    return meta


def song_path(song_id: str) -> str | None:
    meta = get_song(song_id)
    if not meta:
        return None
    p = os.path.join(song_dir(song_id), meta.get("file") or "song.mp3")
    return p if os.path.isfile(p) else None


def list_songs(query: str = "", favorites: bool = False, sort: str = "newest") -> list[dict]:
    if not os.path.isdir(LIBRARY_DIR):
        return []
    songs = []
    q = (query or "").strip().lower()
    for name in os.listdir(LIBRARY_DIR):
        meta = get_song(name)
        if not meta:
            continue
        if favorites and not meta.get("favorite"):
            continue
        if q:
            hay = " ".join(str(meta.get(k) or "") for k in
                           ("title", "caption", "lyrics", "description", "task", "tags")).lower()
            if q not in hay:
                continue
        songs.append(meta)
    key = {"newest": lambda m: -(m.get("created") or 0),
           "oldest": lambda m: (m.get("created") or 0),
           "title": lambda m: (m.get("title") or "").lower(),
           "longest": lambda m: -(m.get("duration") or 0)}.get(sort) or (lambda m: -(m.get("created") or 0))
    songs.sort(key=key)
    return songs


def update_song(song_id: str, patch: dict) -> dict | None:
    allowed = {"title", "favorite", "lyrics", "caption", "tags", "notes", "lrc", "art_prompt"}
    with _lock:
        meta = get_song(song_id)
        if not meta:
            return None
        for k, v in patch.items():
            if k in allowed:
                meta[k] = v
        if not meta.get("title"):
            meta["title"] = derive_title({**meta, "title": ""})
        _write_json(os.path.join(song_dir(song_id), "meta.json"), meta)
    return meta


def delete_song(song_id: str) -> bool:
    try:
        d = song_dir(song_id)
    except ValueError:
        return False
    if not os.path.isdir(d):
        return False
    shutil.rmtree(d)
    return True


def art_path(song_id: str) -> str:
    return os.path.join(song_dir(song_id), "cover.png")


def stems_dir(song_id: str) -> str:
    return os.path.join(song_dir(song_id), "stems")


def download_name(meta: dict) -> str:
    ext = os.path.splitext(meta.get("file") or "song.mp3")[1]
    return _safe_name(meta.get("title") or "", "song") + ext


# -- uploads ----------------------------------------------------------------

def upload_path(upload_id: str) -> str | None:
    if not re.fullmatch(r"[\w-]+", upload_id or ""):
        return None
    meta = _read_json(os.path.join(UPLOADS_DIR, upload_id + ".json"))
    if not meta:
        return None
    p = os.path.join(UPLOADS_DIR, meta["file"])
    return p if os.path.isfile(p) else None


def add_upload(stream, filename: str) -> dict:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(f"Unsupported audio type {ext or '(none)'}. Use mp3, wav, m4a, flac, ogg or aiff.")
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    upload_id = _new_id()
    dst = os.path.join(UPLOADS_DIR, upload_id + ext)
    with open(dst, "wb") as f:
        shutil.copyfileobj(stream, f)
    meta = {"id": upload_id, "name": os.path.basename(filename), "file": upload_id + ext,
            "created": time.time(), "duration": probe_duration(dst), "analysis": None, "stems": {}}
    _write_json(os.path.join(UPLOADS_DIR, upload_id + ".json"), meta)
    return meta


def get_upload(upload_id: str) -> dict | None:
    if not re.fullmatch(r"[\w-]+", upload_id or ""):
        return None
    meta = _read_json(os.path.join(UPLOADS_DIR, upload_id + ".json"))
    if meta:
        sd = os.path.join(UPLOADS_DIR, upload_id + "-stems")
        if os.path.isdir(sd):
            meta["stems"] = {os.path.splitext(f)[0]: f for f in sorted(os.listdir(sd))
                             if os.path.splitext(f)[1].lower() in AUDIO_EXTS}
    return meta


def update_upload(upload_id: str, patch: dict) -> dict | None:
    with _lock:
        meta = get_upload(upload_id)
        if not meta:
            return None
        for k in ("analysis", "name", "notes"):
            if k in patch:
                meta[k] = patch[k]
        _write_json(os.path.join(UPLOADS_DIR, upload_id + ".json"), meta)
    return meta


def list_uploads() -> list[dict]:
    if not os.path.isdir(UPLOADS_DIR):
        return []
    out = []
    for f in os.listdir(UPLOADS_DIR):
        if f.endswith(".json"):
            meta = get_upload(f[:-5])
            if meta:
                out.append(meta)
    out.sort(key=lambda m: -(m.get("created") or 0))
    return out


def delete_upload(upload_id: str) -> bool:
    meta = get_upload(upload_id)
    if not meta:
        return False
    for p in (os.path.join(UPLOADS_DIR, meta["file"]), os.path.join(UPLOADS_DIR, upload_id + ".json")):
        if os.path.exists(p):
            os.remove(p)
    sd = os.path.join(UPLOADS_DIR, upload_id + "-stems")
    if os.path.isdir(sd):
        shutil.rmtree(sd)
    return True


def upload_stems_dir(upload_id: str) -> str:
    return os.path.join(UPLOADS_DIR, upload_id + "-stems")


def resolve_source(kind: str, ident: str) -> str | None:
    """A 'source' in the UI is either an upload or a song already in the library."""
    if kind == "upload":
        return upload_path(ident)
    if kind == "song":
        return song_path(ident)
    if kind == "stem":
        # ident = "<song|upload>:<id>:<stem>"
        parts = ident.split(":", 2)
        if len(parts) != 3:
            return None
        owner, oid, stem = parts
        base = stems_dir(oid) if owner == "song" else upload_stems_dir(oid)
        if not re.fullmatch(r"[\w-]+", stem):
            return None
        for ext in (".mp3", ".wav", ".flac"):
            p = os.path.join(base, stem + ext)
            if os.path.isfile(p):
                return p
    return None
