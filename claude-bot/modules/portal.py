"""Portals — one-off jump links between two channels (Fletcher's `!teleport`).

A "portal" is NOT a mirror. It posts a short message in each of two channels,
each a clickable Discord jump-link to the other. The classic use: you're chatting
in #here and want to carry the conversation to #there without losing stride, so
you drop a portal. People in #here click through to #there, and a back-link in
#there points home. Nothing is bridged or relayed; these are just two messages
that link to each other. No webhooks, no DB, no state to clean up.

This replaces the earlier webhook-mirror implementation, which was the wrong
feature (Fletcher's `!bridge`, not its `!portal`/`!teleport`).

Commands (anyone can use them):
  !portal #other        | !teleport #other | !tp #other
  /portal channel:#other

Channels resolve from a #mention, raw id, channel name (searched across every
server the bot is in), or a Discord message/channel URL. The bot only needs
**Send Messages** + **Embed Links** in both channels.
"""

from __future__ import annotations

import logging
import re

import discord

from handler import Context

log = logging.getLogger("fletcher")

# .../channels/<guild>/<channel>[/<message>]  or a bare <#id> / id / #name
_URL_RE = re.compile(r"/channels/\d+/(\d+)")
_MENTION_RE = re.compile(r"^<#(\d+)>$")


def _jump_url(channel: discord.abc.GuildChannel, message_id: int) -> str:
    return f"https://discord.com/channels/{channel.guild.id}/{channel.id}/{message_id}"


def setup(ctx: Context) -> None:
    if not ctx.config.section("portal").get("enabled", True):
        log.info("portal module disabled in config")
        return

    client = ctx.client
    q = ctx.quips

    q.add("portal", [
        "Mind the gap 🫡",
        "After you 👀",
        "Right this way ✨",
        "Step through ^_^",
        "Door's open, go on 🫡",
    ])

    def resolve_channel(arg: str) -> discord.TextChannel | None:
        """A #mention, raw id, Discord URL, or channel name -> TextChannel.
        Names are searched across every guild the bot can see (portals may
        cross servers, just like Fletcher's)."""
        arg = arg.strip()
        m = _MENTION_RE.match(arg) or _URL_RE.search(arg)
        if m:
            chan = client.get_channel(int(m.group(1)))
            return chan if isinstance(chan, discord.TextChannel) else None
        if arg.isdigit():
            chan = client.get_channel(int(arg))
            return chan if isinstance(chan, discord.TextChannel) else None
        name = arg.lstrip("#").lower()
        for guild in client.guilds:
            for chan in guild.text_channels:
                if chan.name.lower() == name:
                    return chan
        return None

    async def open_portal(here: discord.TextChannel, other: discord.TextChannel,
                          opener: discord.abc.User) -> tuple[str, bool]:
        """Post a cross-linked jump message in each channel. Returns
        (status text for the invoker, ok)."""
        if other.id == here.id:
            return "I can't open a portal from a channel to itself ^_^", False
        # Post in the destination first so we have its message id to link back to,
        # then post in the origin linking forward, then edit the destination to
        # point at the origin message. Two messages, cross-linked.
        try:
            there_msg = await other.send(
                f"🌀 **Portal** from {here.mention} (opened by {opener.mention}). "
                f"Setting up the link...",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            here_msg = await here.send(
                f"🌀 **Portal** to {other.mention} → "
                f"[**jump over**]({_jump_url(there_msg.channel, there_msg.id)})",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await there_msg.edit(
                content=(f"🌀 **Portal** from {here.mention} (opened by {opener.mention}) → "
                         f"[**jump back**]({_jump_url(here_msg.channel, here_msg.id)})"),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            return ("I need **Send Messages** (and Embed Links) in both channels to "
                    "open a portal. Mind granting that? ^_^"), False
        except discord.HTTPException:
            log.exception("portal link creation failed")
            return "Something went sideways opening the portal. >_<", False
        # The origin message already shows the forward link; the command invoker
        # gets a tidy confirmation (or for slash, this is the ephemeral reply).
        return f"🌀 Portal up: {here.mention} ↔ {other.mention}.", True

    # ---- prefix command: !portal / !teleport / !tp -------------------------

    @ctx.handler.command(
        "!portal", "!teleport", "!tp",
        description="Drop a one-off jump link between this channel and another: `!portal #other`",
        min_args=1,
        cooldown=5.0,
    )
    async def portal_cmd(message: discord.Message, args: list[str], ctx: Context):  # noqa: ARG001
        if not isinstance(message.channel, discord.TextChannel):
            await message.reply("Portals only work from a normal text channel.", mention_author=False)
            return
        other = resolve_channel(" ".join(args))
        if other is None:
            await message.reply(
                f"I can't find a channel matching `{' '.join(args)}`. Try `!portal #channel`. >_<",
                mention_author=False)
            return
        text, ok = await open_portal(message.channel, other, message.author)
        # On success the visible portal messages are already posted; just react
        # so we don't double up. On failure, surface why.
        if ok:
            try:
                await message.add_reaction("🌀")
            except discord.HTTPException:
                pass
        else:
            await message.reply(text, mention_author=False)

    # ---- slash command: /portal channel:#other -----------------------------

    if ctx.tree is not None:
        from discord import app_commands

        @app_commands.command(name="portal", description="Drop a one-off jump link to another channel")
        @app_commands.describe(channel="The channel to open a portal to")
        @app_commands.guild_only()
        async def portal_slash(interaction: discord.Interaction, channel: discord.TextChannel):
            here = interaction.channel
            if not isinstance(here, discord.TextChannel):
                await interaction.response.send_message(
                    "Portals only work from a normal text channel.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            text, ok = await open_portal(here, channel, interaction.user)
            await interaction.followup.send(
                ctx.quips.tag(text, "portal") if ok else text, ephemeral=True)

        ctx.tree.add_command(portal_slash, guilds=[discord.Object(id=g) for g in ctx.config.guild_ids])

    log.info("portal ready — one-off jump links (!portal / !teleport / !tp + /portal)")
