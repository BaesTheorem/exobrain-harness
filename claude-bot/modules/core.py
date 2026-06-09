"""Core commands: help + ping. Proves the dispatch lifecycle end to end
(prefix parse -> find -> permission -> cooldown -> invoke) and gives the
Phase 1 skeleton something runnable.

Feature phases plug in alongside this as modules/fun.py, modules/moderation.py,
modules/schedule.py, modules/chatter.py, each with its own setup(ctx).
"""

from __future__ import annotations

import time

import discord

from handler import Context

_START = time.monotonic()


def setup(ctx: Context) -> None:
    h = ctx.handler
    name = ctx.config.name
    prefix = ctx.config.prefix

    @h.command("!help", "!commands", description="List available commands")
    async def help_cmd(message: discord.Message, args: list[str], ctx: Context):
        is_admin = h.is_admin(message.author)
        lines = [f"**{name}** commands:"]
        for cmd in sorted(h.commands, key=lambda c: c.triggers[0]):
            if cmd.hidden:
                continue
            if cmd.admin and not is_admin:
                continue
            triggers = " / ".join(f"`{t}`" for t in cmd.triggers)
            tag = " *(admin)*" if cmd.admin else ""
            lines.append(f"{triggers}{tag} — {cmd.description or 'no description'}")
        await message.channel.send("\n".join(lines))

    @h.command("!ping", description="Check that the bot is alive", cooldown=3.0)
    async def ping_cmd(message: discord.Message, args: list[str], ctx: Context):
        latency_ms = round(ctx.client.latency * 1000)
        uptime = round(time.monotonic() - _START)
        await message.reply(
            f"🏓 {name} is up. Gateway latency {latency_ms}ms, uptime {uptime}s.",
            mention_author=False,
        )

    @h.command("!about", description=f"About {name}")
    async def about_cmd(message: discord.Message, args: list[str], ctx: Context):
        await message.reply(
            f"I'm **{name}**, a single-server bot modeled on the open-source "
            f"Fletcher bot. Type `{prefix}help` to see what I can do.",
            mention_author=False,
        )
