"""MIST — Discord bot entry point.

A stripped-down, modern reimagining of the ~nova/Fletcher Discord bot, scoped
to ONE private Discord server. No sharding, no cross-server bridge engine, no
per-guild config cascade, no hot reload — just a single discord.py gateway
client with a command registry and pluggable feature modules. The running bot
is named "MIST" (config.name); "Fletcher" is the upstream we model.

Run:  .venv/bin/python bot.py
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

import discord

import modules
from config import Config, load_token
from db import DB
from handler import Context, Handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("fletcher")


def build_intents() -> discord.Intents:
    """We need message content (read commands/chat), members (join/leave
    features), reactions (reaction-roles, spoilers), and voice (optional).
    message_content and members are PRIVILEGED — enable them in the Discord
    Developer Portal or the gateway connection will be rejected."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    intents.voice_states = True
    intents.presences = False
    return intents


class FletcherBot(discord.Client):
    def __init__(self, config: Config, db: DB):
        super().__init__(intents=build_intents())
        self.config = config
        self.db = db
        self.handler = Handler(config, db)
        self.ctx = Context(self, config, db, self.handler)

    def load_modules(self) -> None:
        """Import every module under modules/ and call its setup(ctx).
        This is our clean version of Fletcher's autoload(ch) loop."""
        for info in pkgutil.iter_modules(modules.__path__):
            mod = importlib.import_module(f"modules.{info.name}")
            if hasattr(mod, "setup"):
                mod.setup(self.ctx)
                log.info("loaded module: %s", info.name)
        log.info("registered %d commands", len(self.handler.commands))

    async def on_ready(self):
        guild = self.get_guild(self.config.guild_id)
        log.info(
            "%s connected as %s (%s) — serving guild: %s",
            self.config.name,
            self.user, self.user.id if self.user else "?",
            guild.name if guild else f"<{self.config.guild_id} not found>",
        )
        await self.change_presence(activity=discord.Game(name=f"{self.config.prefix}help"))

    async def on_message(self, message: discord.Message):
        await self.handler.dispatch(message, self.ctx)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if self.user and payload.user_id == self.user.id:
            return
        for fn in self.handler.reaction_add_handlers:
            await fn(payload, self.ctx)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if self.user and payload.user_id == self.user.id:
            return
        for fn in self.handler.reaction_remove_handlers:
            await fn(payload, self.ctx)

    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.config.guild_id:
            return
        for fn in self.handler.member_join_handlers:
            await fn(member, self.ctx)

    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != self.config.guild_id:
            return
        for fn in self.handler.member_remove_handlers:
            await fn(member, self.ctx)


def main() -> None:
    config = Config()
    db = DB()
    bot = FletcherBot(config, db)
    bot.load_modules()
    bot.run(load_token(), log_handler=None)


if __name__ == "__main__":
    main()
