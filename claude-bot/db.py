"""SQLite persistence for the single-server Fletcher bot.

One file, no server to run. Fletcher uses Postgres because it spans 100+
guilds; for one private server SQLite is plenty, and FTS5 covers the
chat-history search the LLM persona wants. Postgres ARRAY columns
(sentinel.subscribers, permaroles.roles) become JSON text here.

Schema is created idempotently on init(). Each feature module owns its
own tables; Phase 1 ships the shared ones so later phases just fill them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "claudebot.db"

SCHEMA = """
-- Role save/restore on leave/rejoin (Fletcher: permaroles)
CREATE TABLE IF NOT EXISTS permaroles (
    user_id  INTEGER PRIMARY KEY,
    roles    TEXT NOT NULL,           -- JSON array of role ids
    nickname TEXT,
    updated  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Reaction-role messages: react with emoji on message -> get role
CREATE TABLE IF NOT EXISTS reaction_roles (
    message_id INTEGER NOT NULL,
    emoji      TEXT NOT NULL,         -- unicode char or "<:name:id>"
    role_id    INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);

-- Collective-action pledge mechanic (Fletcher: sentinel)
CREATE TABLE IF NOT EXISTS sentinel (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT UNIQUE,
    description  TEXT,
    subscribers  TEXT NOT NULL DEFAULT '[]',   -- JSON array of user ids
    triggercount INTEGER NOT NULL,
    created      TEXT DEFAULT CURRENT_TIMESTAMP,
    triggered    TEXT,                          -- NULL until threshold hit
    lastmodified TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Reminders, polled by the scheduler loop
CREATE TABLE IF NOT EXISTS reminders (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    content   TEXT,
    scheduled TEXT NOT NULL,           -- ISO-8601 UTC
    recurrence TEXT,                   -- e.g. "every 1 day", or NULL
    created   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (scheduled);

-- Generic per-user key/value (Fletcher: user_preferences)
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (user_id, key)
);

-- LLM chat history, with full-text search for the persona's recall
CREATE TABLE IF NOT EXISTS chatter_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    thread_id  INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE VIRTUAL TABLE IF NOT EXISTS chatter_fts
    USING fts5(content, content='chatter_messages', content_rowid='id');

-- Live channel portals (Fletcher: webhook bridge). Each row is ONE DIRECTION:
-- messages posted in src_channel_id are mirrored into dst_channel_id through a
-- webhook (dst_webhook_id/token) we own on the destination. A two-way portal is
-- two rows, A->B and B->A. Survives restart (rebuilt from this table on boot).
CREATE TABLE IF NOT EXISTS bridges (
    src_channel_id INTEGER NOT NULL,
    dst_channel_id INTEGER NOT NULL,
    dst_guild_id   INTEGER NOT NULL,
    dst_webhook_id INTEGER NOT NULL,
    dst_webhook_token TEXT NOT NULL,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (src_channel_id, dst_channel_id)
);
CREATE INDEX IF NOT EXISTS bridges_src ON bridges (src_channel_id);

-- Routing table: maps a source message to each mirrored copy so edits, deletes
-- and reactions propagate. One row per (source message, destination copy).
CREATE TABLE IF NOT EXISTS bridge_messagemap (
    src_channel_id INTEGER NOT NULL,
    src_message_id INTEGER NOT NULL,
    dst_channel_id INTEGER NOT NULL,
    dst_message_id INTEGER NOT NULL,
    dst_webhook_id INTEGER NOT NULL,
    dst_webhook_token TEXT NOT NULL,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (src_channel_id, src_message_id, dst_channel_id)
);
CREATE INDEX IF NOT EXISTS bridge_map_src ON bridge_messagemap (src_message_id);
CREATE INDEX IF NOT EXISTS bridge_map_dst ON bridge_messagemap (dst_message_id);

-- Race buffer: an edit/delete can arrive before the relay has written the
-- messagemap row for the original. We park a tombstone here and replay it the
-- moment the map row lands; a TTL sweep drops stale ones. (Fletcher:
-- bridge_pending — "any replication that skips this silently drops fast edits".)
CREATE TABLE IF NOT EXISTS bridge_pending (
    src_channel_id INTEGER NOT NULL,
    src_message_id INTEGER NOT NULL,
    action         TEXT NOT NULL,      -- 'edit' | 'delete'
    payload        TEXT,               -- JSON: {"content": "..."} for edits
    created_at     REAL NOT NULL,      -- epoch seconds, for the TTL sweep
    PRIMARY KEY (src_channel_id, src_message_id, action)
);
"""


class DB:
    def __init__(self, path: Path = DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- small helpers used across modules ---
    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def get_pref(self, user_id: int, key: str, default=None):
        row = self.conn.execute(
            "SELECT value FROM user_prefs WHERE user_id=? AND key=?",
            (user_id, key),
        ).fetchone()
        return json.loads(row["value"]) if row else default

    def set_pref(self, user_id: int, key: str, value) -> None:
        self.execute(
            "INSERT INTO user_prefs(user_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (user_id, key, json.dumps(value)),
        )
