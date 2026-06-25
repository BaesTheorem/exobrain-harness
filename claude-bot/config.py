"""Configuration loading for the single-server bot.

The running bot is named "MIST"; its architecture is modeled on the
open-source ~nova/Fletcher Discord bot (references to Fletcher in this repo
are upstream provenance, not the bot's own name).

Two sources, kept deliberately separate so secrets and private IDs never
land in tracked files:

  1. The bot token — read from the *existing* Exobrain env file
     (~/.claude/channels/discord/.env, key DISCORD_BOT_TOKEN), the same
     token the discord-digest fetcher already uses. We reuse it rather
     than copying the secret into this project.

  2. Everything else (guild id, admin ids, per-channel overrides, API
     keys) — read from config.toml in this directory. That file is
     gitignored because guild/channel IDs are private friend-group data.
     See config.example.toml for the shape.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = Path.home() / ".claude" / "channels" / "discord" / ".env"
# The harness root .env holds DISCORD_ALEX_USERNAME (the bot's owner handle),
# used by the chatter module to gate "only ever reply to me".
HARNESS_ENV = HERE.parent / ".env"
CONFIG_FILE = HERE / "config.toml"


def _read_env_key(name: str) -> str | None:
    """Look up a key in the process environment, falling back to the shared
    Exobrain discord .env file. Returns None if not found anywhere."""
    val = os.environ.get(name)
    if val:
        return val.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return None


def load_token() -> str:
    """Read DISCORD_BOT_TOKEN from the environment, falling back to the
    shared Exobrain .env file. Raises if neither is set."""
    token = _read_env_key("DISCORD_BOT_TOKEN")
    if token:
        return token
    raise RuntimeError(
        f"No DISCORD_BOT_TOKEN in environment or {ENV_FILE}. "
        "Set it in the env file or export it before running."
    )


def load_owner_username() -> str | None:
    """The handle of the bot's owner (Alex). The chatter module only ever
    replies to this user. Read from [chatter].owner_username in config.toml
    if set, else DISCORD_ALEX_USERNAME from the harness root .env."""
    if HARNESS_ENV.exists():
        for line in HARNESS_ENV.read_text().splitlines():
            if line.startswith("DISCORD_ALEX_USERNAME="):
                return line.split("=", 1)[1].strip()
    return None


class Config:
    """Flat, single-guild config. No per-guild cascade — this bot lives in
    exactly one server. Per-*channel* overrides are still supported via the
    [channel.<id>] tables, resolved by get()."""

    def __init__(self, path: Path = CONFIG_FILE):
        if not path.exists():
            raise RuntimeError(
                f"{path} not found. Copy config.example.toml to config.toml "
                "and fill in your guild id and admin id(s)."
            )
        with path.open("rb") as f:
            self._d = tomllib.load(f)

        bot = self._d["bot"]
        # Display name used in user-facing text and the LLM persona.
        # Defaults to "MIST" (override in config.toml if you rename it).
        self.name: str = bot.get("name", "MIST")
        self.guild_id: int = int(bot["guild_id"])
        self.prefix: str = bot.get("prefix", "!")
        self.admin_ids: set[int] = {int(x) for x in bot.get("admin_ids", [])}
        self.mod_role_id: int | None = bot.get("mod_role_id")
        self._channels: dict[str, dict] = self._d.get("channel", {})

    def get(self, key: str, channel_id: int | None = None, default=None):
        """Channel override -> global [bot] section -> default."""
        if channel_id is not None:
            chan = self._channels.get(str(channel_id))
            if chan and key in chan:
                return chan[key]
        return self._d.get("bot", {}).get(key, default)

    def section(self, name: str) -> dict:
        """Return a whole top-level table (e.g. 'chatter', 'greeting')."""
        return self._d.get(name, {})
