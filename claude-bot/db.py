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

-- Generic per-user key/value (Fletcher: user_preferences). guild_id 0 is a
-- global row; a guild-specific row overrides it when a lookup allows the
-- global fallback (Fletcher uses NULL for global, but NULL can't sit in a
-- SQLite composite key and still upsert).
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id  INTEGER NOT NULL,
    guild_id INTEGER NOT NULL DEFAULT 0,
    key      TEXT NOT NULL,
    value    TEXT,
    PRIMARY KEY (user_id, guild_id, key)
);
CREATE INDEX IF NOT EXISTS user_prefs_key ON user_prefs (key);

-- Threads the auto-join module has already summoned people into, so a
-- restart or a late gateway replay never summons twice.
CREATE TABLE IF NOT EXISTS thread_summoned (
    thread_id INTEGER PRIMARY KEY,
    guild_id  INTEGER NOT NULL,
    summoned  TEXT DEFAULT CURRENT_TIMESTAMP
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

-- Bot-wide runtime settings that survive a restart (chatter model, effort)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Note: the old webhook-mirror portal (bridges / bridge_messagemap /
# bridge_pending) was removed in favor of one-off jump-link portals
# (modules/portal.py), which keep no state. Those tables are dropped on init if
# they linger from an older DB.
_DROP_LEGACY = (
    "DROP TABLE IF EXISTS bridge_pending",
    "DROP TABLE IF EXISTS bridge_messagemap",
    "DROP TABLE IF EXISTS bridges",
)


class DB:
    def __init__(self, path: Path = DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate_user_prefs()
        self.conn.executescript(SCHEMA)
        for stmt in _DROP_LEGACY:
            self.conn.execute(stmt)
        self.conn.commit()

    # --- small helpers used across modules ---
    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def _migrate_user_prefs(self) -> None:
        """The first schema keyed user_prefs on (user_id, key) with no guild
        column. Nothing ever wrote to it, so rebuild rather than ALTER."""
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(user_prefs)")]
        if cols and "guild_id" not in cols:
            self.conn.execute("DROP TABLE user_prefs")
            self.conn.commit()

    def get_pref(self, user_id: int, key: str, default=None, guild_id: int = 0,
                 allow_global: bool = False):
        """Read one preference. guild_id 0 is the global row. With
        allow_global, a guild lookup falls back to the global row (guild wins
        when both exist)."""
        if guild_id and allow_global:
            row = self.conn.execute(
                "SELECT value FROM user_prefs WHERE user_id=? AND key=? "
                "AND guild_id IN (?, 0) ORDER BY guild_id DESC LIMIT 1",
                (user_id, key, guild_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT value FROM user_prefs WHERE user_id=? AND guild_id=? AND key=?",
                (user_id, guild_id, key),
            ).fetchone()
        return json.loads(row["value"]) if row else default

    def set_pref(self, user_id: int, key: str, value, guild_id: int = 0) -> None:
        self.execute(
            "INSERT INTO user_prefs(user_id,guild_id,key,value) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,guild_id,key) DO UPDATE SET value=excluded.value",
            (user_id, guild_id, key, json.dumps(value)),
        )

    def del_pref(self, user_id: int, key: str, guild_id: int = 0) -> bool:
        cur = self.execute(
            "DELETE FROM user_prefs WHERE user_id=? AND guild_id=? AND key=?",
            (user_id, guild_id, key),
        )
        return cur.rowcount > 0

    def users_with_pref(self, key: str, guild_id: int) -> list[int]:
        """Every user holding `key` for this guild or globally."""
        rows = self.conn.execute(
            "SELECT DISTINCT user_id FROM user_prefs WHERE key=? AND guild_id IN (?, 0)",
            (key, guild_id),
        ).fetchall()
        return [r["user_id"] for r in rows]

    def thread_summoned(self, thread_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM thread_summoned WHERE thread_id=?", (thread_id,)
        ).fetchone()
        return row is not None

    def mark_thread_summoned(self, thread_id: int, guild_id: int) -> None:
        self.execute(
            "INSERT OR IGNORE INTO thread_summoned(thread_id,guild_id) VALUES(?,?)",
            (thread_id, guild_id),
        )

    def get_setting(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
