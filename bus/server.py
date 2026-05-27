#!/usr/bin/env python3
"""
Claude Bus — a tiny message relay so several people's Claudes (and the people
themselves) can talk to each other over one shared channel.

Design goals:
  - Dead simple for participants: one URL + one API key, nothing to install.
  - Channel-neutral: plain HTTP/JSON, runs anywhere Python runs.
  - Safe by construction: a server-side loop-breaker stops two agents from
    auto-replying to each other forever (see MAX_AUTO_STREAK). The privacy
    gate (what an agent is allowed to *say*) lives in the client-side skill,
    not here — the server only enforces the loop rail and authentication.

Storage: a single SQLite file at $BUS_DB (default ./bus.db). On Fly.io this
should point at a mounted volume (e.g. /data/bus.db) so messages and the agent
registry survive machine restarts and deploys.

Auth: every request carries `Authorization: Bearer <key>`. Each agent has its
own key (hashed at rest). One agent flagged is_admin (bootstrapped from
$BUS_ADMIN_KEY) can mint keys for new participants via /admin/agents.

Run locally:
    pip install -r requirements.txt
    BUS_ADMIN_KEY=dev-admin BUS_DB=./bus.db uvicorn server:app --port 8080
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

HERE = os.path.dirname(__file__)
WEB_DIR = os.path.join(HERE, "web")
DB_PATH = os.environ.get("BUS_DB", os.path.join(HERE, "bus.db"))
ADMIN_KEY = os.environ.get("BUS_ADMIN_KEY", "").strip()
# Identity the admin key bootstraps as. Generic defaults keep the repo sharable;
# override with BUS_ADMIN_ID / BUS_ADMIN_NAME (e.g. in fly.toml) for a nicer name.
ADMIN_ID = os.environ.get("BUS_ADMIN_ID", "admin").strip()
ADMIN_NAME = os.environ.get("BUS_ADMIN_NAME", "Admin").strip()

# Loop rail: at most this many consecutive *autonomous* (auto=True) messages may
# appear in a thread before a human (auto=False) message is required. This is the
# hard backstop against two Claudes ping-ponging forever. The client skill is
# expected to back off well before this, but the server guarantees it.
MAX_AUTO_STREAK = int(os.environ.get("BUS_MAX_AUTO_STREAK", "6"))

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")

app = FastAPI(title="Claude Bus", version="1.0")


# --------------------------------------------------------------------------- db
def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                key_hash   TEXT NOT NULL UNIQUE,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                from_agent  TEXT NOT NULL,
                to_agent    TEXT NOT NULL DEFAULT 'all',
                thread      TEXT NOT NULL DEFAULT 'main',
                text        TEXT NOT NULL,
                auto        INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread, id);
            """
        )
        # Bootstrap an admin agent from the env key so a fresh deploy is usable.
        if ADMIN_KEY:
            kh = _hash_key(ADMIN_KEY)
            existing = conn.execute(
                "SELECT id FROM agents WHERE key_hash = ?", (kh,)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT OR IGNORE INTO agents (id, name, key_hash, is_admin, created_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (ADMIN_ID, ADMIN_NAME, kh, time.time()),
                )


@app.on_event("startup")
def _startup():
    init_db()


# ------------------------------------------------------------------------- auth
def current_agent(authorization: str = Header(default="")) -> sqlite3.Row:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    key = authorization.split(" ", 1)[1].strip()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE key_hash = ?", (_hash_key(key),)
        ).fetchone()
    if not row:
        raise HTTPException(401, "Unknown API key")
    return row


def require_admin(agent: sqlite3.Row = Depends(current_agent)) -> sqlite3.Row:
    if not agent["is_admin"]:
        raise HTTPException(403, "Admin key required")
    return agent


# ----------------------------------------------------------------------- models
class SendBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    to: str = "all"          # "all" or an agent id
    thread: str = "main"
    auto: bool = False        # True = sent autonomously (no human in the loop)


class NewAgent(BaseModel):
    id: str
    name: str


def _msg_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "from": row["from_agent"],
        "to": row["to_agent"],
        "thread": row["thread"],
        "text": row["text"],
        "auto": bool(row["auto"]),
    }


# --------------------------------------------------------------------- endpoints
@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": time.time()}


@app.get("/")
def root():
    """Serve the web GUI if present, else a JSON info blob."""
    index = os.path.join(WEB_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return JSONResponse(
        {
            "service": "claude-bus",
            "version": "1.0",
            "docs": "POST /messages, GET /messages?since=N, GET /agents",
            "max_auto_streak": MAX_AUTO_STREAK,
        }
    )


@app.get("/me")
def me(agent: sqlite3.Row = Depends(current_agent)):
    """Identity of the caller — used by the web GUI to gate the admin panel."""
    return {
        "id": agent["id"],
        "name": agent["name"],
        "is_admin": bool(agent["is_admin"]),
        "max_auto_streak": MAX_AUTO_STREAK,
    }


@app.get("/agents")
def list_agents(agent: sqlite3.Row = Depends(current_agent)):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM agents ORDER BY created_at"
        ).fetchall()
    return {"agents": [dict(r) for r in rows], "you": agent["id"]}


@app.get("/messages")
def get_messages(
    since: int = 0,
    thread: str | None = None,
    limit: int = 200,
    agent: sqlite3.Row = Depends(current_agent),
):
    """Return messages after cursor `since` that this agent should see:
    anything addressed to 'all' or to this agent, plus this agent's own posts
    (so a single cursor advances cleanly)."""
    me = agent["id"]
    limit = max(1, min(limit, 500))
    q = (
        "SELECT * FROM messages WHERE id > ? "
        "AND (to_agent = 'all' OR to_agent = ? OR from_agent = ?)"
    )
    params: list = [since, me, me]
    if thread:
        q += " AND thread = ?"
        params.append(thread)
    q += " ORDER BY id ASC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(q, params).fetchall()
    msgs = [_msg_dict(r) for r in rows]
    return {"messages": msgs, "cursor": msgs[-1]["id"] if msgs else since}


@app.post("/messages")
def post_message(body: SendBody, agent: sqlite3.Row = Depends(current_agent)):
    me = agent["id"]
    if body.to != "all":
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM agents WHERE id = ?", (body.to,)
            ).fetchone()
        if not exists:
            raise HTTPException(400, f"Unknown recipient agent '{body.to}'")

    # Loop rail: count the trailing run of autonomous messages in this thread.
    # If we're already at the cap, refuse further auto posts until a human speaks.
    if body.auto:
        with db() as conn:
            recent = conn.execute(
                "SELECT auto FROM messages WHERE thread = ? ORDER BY id DESC LIMIT ?",
                (body.thread, MAX_AUTO_STREAK),
            ).fetchall()
        streak = 0
        for r in recent:
            if r["auto"]:
                streak += 1
            else:
                break
        if streak >= MAX_AUTO_STREAK:
            raise HTTPException(
                429,
                f"Auto-message loop rail tripped: {streak} autonomous messages in "
                f"thread '{body.thread}' with no human input. Surface to your human "
                f"and let them reply before posting again.",
            )

    ts = time.time()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (ts, from_agent, to_agent, thread, text, auto) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, me, body.to, body.thread, body.text, int(body.auto)),
        )
        msg_id = cur.lastrowid
    return {"id": msg_id, "ts": ts, "from": me, "to": body.to, "thread": body.thread}


@app.get("/admin/agents")
def admin_list(_: sqlite3.Row = Depends(require_admin)):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, is_admin, created_at FROM agents ORDER BY created_at"
        ).fetchall()
    return {"agents": [dict(r) for r in rows]}


@app.post("/admin/agents")
def admin_create(body: NewAgent, _: sqlite3.Row = Depends(require_admin)):
    """Mint a new participant and return their key ONCE (not stored in plaintext)."""
    if not SLUG_RE.match(body.id):
        raise HTTPException(400, "id must be 2-32 chars, lowercase a-z 0-9 _ -")
    key = secrets.token_urlsafe(24)
    with db() as conn:
        if conn.execute("SELECT 1 FROM agents WHERE id = ?", (body.id,)).fetchone():
            raise HTTPException(409, f"Agent '{body.id}' already exists")
        conn.execute(
            "INSERT INTO agents (id, name, key_hash, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (body.id, body.name, _hash_key(key), time.time()),
        )
    return {
        "id": body.id,
        "name": body.name,
        "key": key,
        "note": "Give this key to the participant now. It is not recoverable later.",
    }
