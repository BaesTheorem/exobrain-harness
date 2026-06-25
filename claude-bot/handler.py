"""Command registry and dispatch — the modern, single-guild equivalent of
Fletcher's CommandHandler.

Fletcher stores commands as plain dicts so it can hot-reload modules via
importlib. We don't need hot reload (single server -> just restart), so we
use a clean dataclass + decorator registry instead. The dispatch lifecycle
mirrors Fletcher's: prefix parse -> find command -> permission check ->
rate-limit -> invoke.

Permission levels collapse from Fletcher's global/server/channel tiers to
just EVERYONE / ADMIN, since "global admin" == you on your own server.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import discord

log = logging.getLogger("fletcher")

# A command handler: (message, args, ctx) -> awaitable. args is the message
# content after the trigger, already split on whitespace.
CommandFn = Callable[[discord.Message, list[str], "Context"], Awaitable[None]]


@dataclass
class Command:
    triggers: tuple[str, ...]
    fn: CommandFn
    description: str = ""
    admin: bool = False
    min_args: int = 0
    cooldown: float = 0.0          # seconds between uses, per user
    hidden: bool = False
    _last_used: dict[int, float] = field(default_factory=dict, repr=False)


class Context:
    """Passed to every command and module. Bundles the shared singletons so
    modules never import each other's state (Fletcher injects these as module
    globals on reload; we pass them explicitly)."""

    def __init__(self, client: discord.Client, config, db, handler: "Handler"):
        self.client = client
        self.config = config
        self.db = db
        self.handler = handler


class Handler:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.commands: list[Command] = []
        # Event handler lists, populated by modules (Fletcher: join_handlers etc.)
        # message_handlers run for messages that are NOT a recognized command
        # (e.g. the chatter module replying to @mentions / DMs). Each returns
        # True if it consumed the message, so later handlers can be skipped.
        self.message_handlers: list[Callable] = []
        self.reaction_add_handlers: list[Callable] = []
        self.reaction_remove_handlers: list[Callable] = []
        self.member_join_handlers: list[Callable] = []
        self.member_remove_handlers: list[Callable] = []

    # --- registration (called by modules in setup()) ---
    def command(self, *triggers: str, **kwargs) -> Callable[[CommandFn], CommandFn]:
        """Decorator: @handler.command('!ping', description='...')"""
        def deco(fn: CommandFn) -> CommandFn:
            self.commands.append(Command(triggers=triggers, fn=fn, **kwargs))
            return fn
        return deco

    def find(self, content: str) -> tuple[Command, list[str]] | None:
        """Match the first token against command triggers (exact, like
        Fletcher's keyword_trie primary mode)."""
        parts = content.split()
        if not parts:
            return None
        trigger = parts[0].lower()
        for cmd in self.commands:
            if trigger in cmd.triggers:
                return cmd, parts[1:]
        return None

    def is_admin(self, member: discord.Member | discord.User) -> bool:
        if member.id in self.config.admin_ids:
            return True
        if isinstance(member, discord.Member):
            if member.guild_permissions.manage_guild:
                return True
            if self.config.mod_role_id and any(
                r.id == self.config.mod_role_id for r in member.roles
            ):
                return True
        return False

    # --- dispatch (called from on_message) ---
    async def dispatch(self, message: discord.Message, ctx: Context) -> bool:
        """Try to handle the message as a prefix command. Returns True if a
        command consumed it (so on_message won't also run message_handlers),
        False if it wasn't a command at all (chatter etc. may handle it)."""
        if message.author.bot:
            return False
        # Single-guild guard for COMMANDS: ignore commands outside our server.
        # DMs are intentionally let through to message_handlers (chatter), but
        # they are never treated as commands here.
        if message.guild is None or message.guild.id != self.config.guild_id:
            return False
        content = message.content.strip()
        if not content.startswith(self.config.prefix):
            return False

        match = self.find(content)
        if match is None:
            return False
        cmd, args = match

        if cmd.admin and not self.is_admin(message.author):
            await message.reply("You don't have permission to use that.", mention_author=False)
            return True

        if len(args) < cmd.min_args:
            await message.reply(
                f"Usage: `{cmd.triggers[0]}` needs at least {cmd.min_args} argument(s).",
                mention_author=False,
            )
            return True

        if cmd.cooldown:
            now = time.monotonic()
            last = cmd._last_used.get(message.author.id, 0.0)
            if now - last < cmd.cooldown:
                wait = cmd.cooldown - (now - last)
                await message.add_reaction("⏳")
                log.debug("rate-limited %s for %s (%.1fs left)", message.author, cmd.triggers[0], wait)
                return True
            cmd._last_used[message.author.id] = now

        try:
            await cmd.fn(message, args, ctx)
        except Exception:
            log.exception("command %s failed", cmd.triggers[0])
            try:
                await message.add_reaction("🚫")
            except discord.HTTPException:
                pass
        return True
