"""Portals — live two-way message bridges between Discord channels.

This is the modern, single-bot rebuild of Fletcher's webhook bridge engine
(`commandhandler.bridge_message` + `janissary !bridge`). A "portal" is a
persistent, **two-way** mirror between two channels — possibly in different
servers. Messages, edits, deletes and reactions made in one side show up in the
other, posted under the *original author's* name and avatar via a webhook we own
on the destination channel.

How it works (mirrors Fletcher's replication-priority order):

  1. **Registry in the DB** (`bridges`). Each row is one direction (src -> dst)
     and holds the destination webhook's id+token. A two-way portal is two rows.
     It's all in SQLite, so portals survive a restart with no rebuild step.
  2. **`bridge_messagemap`** maps every source message to its mirrored copy, so
     edits / deletes / reactions can find and update the copy.
  3. **Loop prevention.** Mirrored messages are webhook messages, and bot.py's
     `on_message` already drops everything from bots/webhooks before the relay
     ever sees it; we also guard on `message.webhook_id` for defense in depth.
  4. **`bridge_pending`.** An edit or delete can land *before* the relay has
     written the messagemap row for the original. We park a tombstone and replay
     it the instant the map row appears, plus a TTL sweep for stale ones.

Commands (admin only):
  !portal #other-channel     open a two-way portal between here and #other
  !portal list               show the active portals
  !portal close #other       tear a portal down (deletes both webhooks)

`!bridge` is an alias for `!portal`. Channels resolve from a #mention, a raw id,
a channel name (searched across every server the bot is in), or a Discord URL.

Known limits (documented, not bugs): only human messages relay (other bots /
webhooks are skipped, which is also what keeps loops impossible); content is
capped at Discord's 2000 chars; cross-server *custom* emoji reactions only
mirror if the destination can already use that emoji; reaction REMOVES are
best-effort.
"""

from __future__ import annotations

import json
import logging
import re
import time

import discord

from handler import Context

log = logging.getLogger("fletcher")

WEBHOOK_NAME = "MIST Portal"
DISCORD_LIMIT = 2000
PENDING_TTL_SEC = 300  # drop unmatched edit/delete tombstones after 5 min

# .../channels/<guild>/<channel>[/<message>]  or a bare <#id> / id / #name
_URL_RE = re.compile(r"/channels/\d+/(\d+)")
_MENTION_RE = re.compile(r"^<#(\d+)>$")


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("bridge")
    if not cfg.get("enabled", True):
        log.info("bridge module disabled in config")
        return

    db = ctx.db
    client = ctx.client

    # ---- channel resolution -------------------------------------------------

    def resolve_channel(arg: str) -> discord.TextChannel | None:
        """A #mention, raw id, Discord URL, or channel name -> TextChannel.
        Names are searched across every guild the bot can see (portals are
        allowed to cross servers, just like Fletcher's bridges)."""
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

    def webhook_for(webhook_id: int, token: str) -> discord.Webhook:
        # `client=` gives the partial webhook a session + state, so send(wait=True)
        # returns a full Message we can record in the messagemap.
        return discord.Webhook.partial(webhook_id, token, client=client)

    # ---- relay content ------------------------------------------------------

    def render(message: discord.Message) -> str:
        """Source message -> text to mirror. clean_content turns mentions into
        plain names so we never ping across a portal; attachments and stickers
        ride along as links/labels."""
        text = (message.clean_content or "").strip()
        extras: list[str] = [a.url for a in message.attachments]
        extras += [f"[sticker: {s.name}]" for s in message.stickers]
        if extras:
            text = (text + "\n" + "\n".join(extras)).strip()
        if len(text) > DISCORD_LIMIT:
            text = text[: DISCORD_LIMIT - 1] + "…"
        return text

    def webhook_username(member: discord.abc.User) -> str:
        # Discord rejects usernames containing "clyde"/"discord" and caps at 80.
        name = getattr(member, "display_name", None) or member.name
        name = re.sub(r"(?i)clyde|discord", "*", name)[:80]
        return name or "someone"

    # ---- pending (race) buffer ---------------------------------------------

    def park_pending(src_channel: int, src_msg: int, action: str, payload: dict | None) -> None:
        db.execute(
            "INSERT OR REPLACE INTO bridge_pending"
            "(src_channel_id, src_message_id, action, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (src_channel, src_msg, action, json.dumps(payload) if payload else None, time.time()),
        )

    async def replay_pending(src_channel: int, src_msg: int) -> None:
        """Called right after a message's map rows are written: apply any edit/
        delete that arrived early, then sweep expired tombstones."""
        db.execute("DELETE FROM bridge_pending WHERE created_at < ?", (time.time() - PENDING_TTL_SEC,))
        rows = db.query(
            "SELECT action, payload FROM bridge_pending WHERE src_channel_id=? AND src_message_id=?",
            (src_channel, src_msg),
        )
        for r in rows:
            payload = json.loads(r["payload"]) if r["payload"] else {}
            if r["action"] == "edit":
                await apply_edit(src_channel, src_msg, payload.get("content"))
            elif r["action"] == "delete":
                await apply_delete(src_channel, src_msg)
        if rows:
            db.execute(
                "DELETE FROM bridge_pending WHERE src_channel_id=? AND src_message_id=?",
                (src_channel, src_msg),
            )

    # ---- edit / delete application -----------------------------------------

    async def apply_edit(src_channel: int, src_msg: int, content: str | None) -> bool:
        rows = db.query(
            "SELECT * FROM bridge_messagemap WHERE src_channel_id=? AND src_message_id=?",
            (src_channel, src_msg),
        )
        for r in rows:
            try:
                await webhook_for(r["dst_webhook_id"], r["dst_webhook_token"]).edit_message(
                    r["dst_message_id"],
                    content=content or "​",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                log.debug("portal edit propagation failed", exc_info=True)
        return bool(rows)

    async def apply_delete(src_channel: int, src_msg: int) -> bool:
        rows = db.query(
            "SELECT * FROM bridge_messagemap WHERE src_channel_id=? AND src_message_id=?",
            (src_channel, src_msg),
        )
        for r in rows:
            try:
                await webhook_for(r["dst_webhook_id"], r["dst_webhook_token"]).delete_message(
                    r["dst_message_id"]
                )
            except discord.HTTPException:
                log.debug("portal delete propagation failed", exc_info=True)
        if rows:
            db.execute(
                "DELETE FROM bridge_messagemap WHERE src_channel_id=? AND src_message_id=?",
                (src_channel, src_msg),
            )
        return bool(rows)

    def is_portal_source(channel_id: int) -> bool:
        return bool(db.query("SELECT 1 FROM bridges WHERE src_channel_id=? LIMIT 1", (channel_id,)))

    # ---- relay: a new message on a portalled channel -----------------------

    async def relay(message: discord.Message, ctx: Context) -> bool:  # noqa: ARG001
        # NEVER consume the message: returning False lets chatter & friends still
        # run. (on_message already dropped bot/webhook messages, so no loop.)
        if message.webhook_id:
            return False
        routes = db.query("SELECT * FROM bridges WHERE src_channel_id=?", (message.channel.id,))
        if not routes:
            return False
        content = render(message)
        if not content:
            return False
        username = webhook_username(message.author)
        avatar = message.author.display_avatar.url
        for r in routes:
            try:
                sent = await webhook_for(r["dst_webhook_id"], r["dst_webhook_token"]).send(
                    content,
                    username=username,
                    avatar_url=avatar,
                    wait=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                log.exception("portal relay send failed")
                continue
            db.execute(
                "INSERT OR REPLACE INTO bridge_messagemap"
                "(src_channel_id, src_message_id, dst_channel_id, dst_message_id,"
                " dst_webhook_id, dst_webhook_token) VALUES (?,?,?,?,?,?)",
                (message.channel.id, message.id, r["dst_channel_id"], sent.id,
                 r["dst_webhook_id"], r["dst_webhook_token"]),
            )
        await replay_pending(message.channel.id, message.id)
        return False

    # Run the relay BEFORE chatter so a message that also @mentions MIST still
    # crosses the portal (chatter would otherwise consume it). relay returns
    # False, so chatter still gets its turn afterward.
    ctx.handler.message_handlers.insert(0, relay)

    # ---- edit / delete events ----------------------------------------------

    @ctx.handler.raw_message_edit_handlers.append
    async def on_edit(payload: discord.RawMessageUpdateEvent, ctx: Context) -> None:  # noqa: ARG001
        # Only content edits are mirrored; embed-only updates carry no 'content'.
        if "content" not in payload.data:
            return
        content = payload.data.get("content")
        if not await apply_edit(payload.channel_id, payload.message_id, content):
            # Map row not written yet (relay still in flight) — park it.
            if is_portal_source(payload.channel_id):
                park_pending(payload.channel_id, payload.message_id, "edit", {"content": content})

    @ctx.handler.raw_message_delete_handlers.append
    async def on_delete(payload: discord.RawMessageDeleteEvent, ctx: Context) -> None:  # noqa: ARG001
        if not await apply_delete(payload.channel_id, payload.message_id):
            if is_portal_source(payload.channel_id):
                park_pending(payload.channel_id, payload.message_id, "delete", None)

    # ---- reactions ----------------------------------------------------------

    def mirror_targets(channel_id: int, message_id: int) -> list[tuple[int, int]]:
        """Given a message that someone reacted to, return the (channel_id,
        message_id) pairs to mirror the reaction onto: the destination copies if
        it's a source message, or the source if it's a mirrored copy."""
        out: list[tuple[int, int]] = []
        for r in db.query(
            "SELECT dst_channel_id, dst_message_id FROM bridge_messagemap "
            "WHERE src_channel_id=? AND src_message_id=?",
            (channel_id, message_id),
        ):
            out.append((r["dst_channel_id"], r["dst_message_id"]))
        for r in db.query(
            "SELECT src_channel_id, src_message_id FROM bridge_messagemap "
            "WHERE dst_channel_id=? AND dst_message_id=?",
            (channel_id, message_id),
        ):
            out.append((r["src_channel_id"], r["src_message_id"]))
        return out

    @ctx.handler.reaction_add_handlers.append
    async def on_react_add(payload: discord.RawReactionActionEvent, ctx: Context) -> None:  # noqa: ARG001
        for chan_id, msg_id in mirror_targets(payload.channel_id, payload.message_id):
            chan = client.get_channel(chan_id)
            if not isinstance(chan, (discord.TextChannel, discord.Thread)):
                continue
            try:
                await chan.get_partial_message(msg_id).add_reaction(payload.emoji)
            except discord.HTTPException:
                log.debug("portal reaction add failed (custom emoji across servers?)", exc_info=True)

    @ctx.handler.reaction_remove_handlers.append
    async def on_react_remove(payload: discord.RawReactionActionEvent, ctx: Context) -> None:  # noqa: ARG001
        # Best-effort: drop the bot's mirrored reaction. (We don't reference-count
        # other users still holding the same reaction — a known minor limitation.)
        for chan_id, msg_id in mirror_targets(payload.channel_id, payload.message_id):
            chan = client.get_channel(chan_id)
            if not isinstance(chan, (discord.TextChannel, discord.Thread)):
                continue
            try:
                await chan.get_partial_message(msg_id).remove_reaction(payload.emoji, client.user)
            except discord.HTTPException:
                log.debug("portal reaction remove failed", exc_info=True)

    # ---- command: !portal / !bridge ----------------------------------------

    @ctx.handler.command(
        "!portal", "!bridge",
        description="Open/close a two-way portal between channels. "
                    "`!portal #chan` | `!portal list` | `!portal close #chan`",
        admin=True,
    )
    async def portal_cmd(message: discord.Message, args: list[str], ctx: Context):  # noqa: ARG001
        if not args:
            await message.reply(
                "Usage: `!portal #other-channel` to open, `!portal list` to see "
                "them, `!portal close #other-channel` to tear one down. ^_^",
                mention_author=False,
            )
            return

        sub = args[0].lower()

        if sub == "list":
            rows = db.query("SELECT src_channel_id, dst_channel_id FROM bridges ORDER BY created_at")
            if not rows:
                await message.reply("No portals open right now. ✨", mention_author=False)
                return
            # Collapse the two directional rows of each portal into one pair.
            seen: set[frozenset] = set()
            lines = ["**Open portals** 🌀"]
            for r in rows:
                pair = frozenset((r["src_channel_id"], r["dst_channel_id"]))
                if pair in seen:
                    continue
                seen.add(pair)
                lines.append(f"<#{r['src_channel_id']}> ⇄ <#{r['dst_channel_id']}>")
            await message.reply("\n".join(lines), mention_author=False)
            return

        if sub == "close":
            if len(args) < 2:
                await message.reply("Which one? `!portal close #other-channel`", mention_author=False)
                return
            other = resolve_channel(args[1])
            if other is None:
                await message.reply(f"I can't find a channel matching `{args[1]}`. >_<", mention_author=False)
                return
            here = message.channel.id
            rows = db.query(
                "SELECT * FROM bridges WHERE (src_channel_id=? AND dst_channel_id=?) "
                "OR (src_channel_id=? AND dst_channel_id=?)",
                (here, other.id, other.id, here),
            )
            if not rows:
                await message.reply("There's no portal between those two channels.", mention_author=False)
                return
            for r in rows:
                try:
                    await webhook_for(r["dst_webhook_id"], r["dst_webhook_token"]).delete(
                        reason="MIST portal closed"
                    )
                except discord.HTTPException:
                    log.debug("portal webhook delete failed (already gone?)", exc_info=True)
            db.execute(
                "DELETE FROM bridges WHERE (src_channel_id=? AND dst_channel_id=?) "
                "OR (src_channel_id=? AND dst_channel_id=?)",
                (here, other.id, other.id, here),
            )
            db.execute(
                "DELETE FROM bridge_messagemap WHERE src_channel_id IN (?,?) OR dst_channel_id IN (?,?)",
                (here, other.id, here, other.id),
            )
            await message.reply(f"Portal to <#{other.id}> closed. ┬─┬ノ( º _ ºノ)", mention_author=False)
            try:
                await other.send("🌀 The portal to this channel was closed.")
            except discord.HTTPException:
                pass
            return

        # default: open a portal between here and the named channel
        other = resolve_channel(" ".join(args))
        if other is None:
            await message.reply(f"I can't find a channel matching `{' '.join(args)}`. >_<", mention_author=False)
            return
        if not isinstance(message.channel, discord.TextChannel):
            await message.reply("Portals can only start from a normal text channel.", mention_author=False)
            return
        here = message.channel
        if other.id == here.id:
            await message.reply("I can't portal a channel to itself, silly ^_^", mention_author=False)
            return
        if db.query(
            "SELECT 1 FROM bridges WHERE src_channel_id=? AND dst_channel_id=? LIMIT 1",
            (here.id, other.id),
        ):
            await message.reply(f"There's already a portal to <#{other.id}>. ✨", mention_author=False)
            return

        try:
            # Webhook on the DESTINATION carries here -> there; webhook on HERE
            # carries there -> here. Two webhooks = one two-way portal.
            wh_there = await other.create_webhook(name=WEBHOOK_NAME, reason="MIST portal")
            wh_here = await here.create_webhook(name=WEBHOOK_NAME, reason="MIST portal")
        except discord.Forbidden:
            await message.reply(
                "I need the **Manage Webhooks** permission in *both* channels to open a portal. "
                "Can you grant that and try again? ^_^",
                mention_author=False,
            )
            return
        except discord.HTTPException:
            log.exception("portal webhook creation failed")
            await message.reply("Something went sideways creating the portal webhooks. >_<", mention_author=False)
            return

        db.execute(
            "INSERT OR REPLACE INTO bridges"
            "(src_channel_id, dst_channel_id, dst_guild_id, dst_webhook_id, dst_webhook_token)"
            " VALUES (?,?,?,?,?)",
            (here.id, other.id, other.guild.id, wh_there.id, wh_there.token),
        )
        db.execute(
            "INSERT OR REPLACE INTO bridges"
            "(src_channel_id, dst_channel_id, dst_guild_id, dst_webhook_id, dst_webhook_token)"
            " VALUES (?,?,?,?,?)",
            (other.id, here.id, here.guild.id, wh_here.id, wh_here.token),
        )
        await message.reply(
            f"🌀✨ Portal open! <#{here.id}> ⇄ <#{other.id}>. Anything said in either "
            f"channel shows up in the other now. (╯°□°)╯︵ ┻━┻",
            mention_author=False,
        )
        try:
            await other.send(f"🌀✨ A two-way portal just opened to <#{here.id}>. Say hi ^_^")
        except discord.HTTPException:
            pass

    log.info("bridge ready — live two-way channel portals via webhooks")
