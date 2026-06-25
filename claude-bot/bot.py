"""MIST — Discord bot entry point.

A stripped-down, modern reimagining of the ~nova/Fletcher Discord bot, scoped
to ONE private Discord server. No sharding, no cross-server bridge engine, no
per-guild config cascade, no hot reload — just a single discord.py gateway
client with a command registry and pluggable feature modules. The running bot
is named "MIST" (config.name); "Fletcher" is the upstream we model.

Run:  .venv/bin/python bot.py
"""

from __future__ import annotations

try:
    import setproctitle
    setproctitle.setproctitle("MIST Discord Bot")
except ImportError:
    pass  # cosmetic process name only; never block startup on it

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
        # Slash (/) command tree. Modules register app commands on it in their
        # setup(); we sync it per-guild in on_ready (guild-scoped syncs are
        # instant, unlike global commands which take up to an hour to appear).
        self.tree = discord.app_commands.CommandTree(self)
        self.ctx = Context(self, config, db, self.handler, self.tree)

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
        served = []
        for gid in self.config.guild_ids:
            g = self.get_guild(gid)
            served.append(g.name if g else f"<{gid} not found>")
        log.info(
            "%s connected as %s (%s) — serving guild(s): %s",
            self.config.name,
            self.user, self.user.id if self.user else "?",
            ", ".join(served),
        )
        await self.change_presence(activity=discord.Game(name=f"{self.config.prefix}help"))
        # Register slash commands with Discord, one guild at a time so they show
        # up instantly. Forbidden => the bot was invited without the
        # `applications.commands` scope and must be re-invited with it.
        for gid in self.config.guild_ids:
            try:
                synced = await self.tree.sync(guild=discord.Object(id=gid))
                log.info("synced %d slash command(s) to guild %s", len(synced), gid)
            except discord.Forbidden:
                log.warning(
                    "slash sync forbidden for guild %s — re-invite the bot with the "
                    "applications.commands scope to enable / commands", gid,
                )
            except discord.HTTPException:
                log.exception("slash command sync failed for guild %s", gid)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # Prefix commands take priority; if none matched, offer the message to
        # the message_handlers (chatter replies to @mentions / replies / DMs).
        handled = await self.handler.dispatch(message, self.ctx)
        if handled:
            return
        for fn in self.handler.message_handlers:
            try:
                if await fn(message, self.ctx):
                    break
            except Exception:
                log.exception("message handler failed")

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        for fn in self.handler.raw_message_edit_handlers:
            try:
                await fn(payload, self.ctx)
            except Exception:
                log.exception("raw message edit handler failed")

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        for fn in self.handler.raw_message_delete_handlers:
            try:
                await fn(payload, self.ctx)
            except Exception:
                log.exception("raw message delete handler failed")

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
        if member.guild.id not in self.config.guild_ids:
            return
        for fn in self.handler.member_join_handlers:
            await fn(member, self.ctx)

    async def on_member_remove(self, member: discord.Member):
        if member.guild.id not in self.config.guild_ids:
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
