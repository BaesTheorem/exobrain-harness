"""Thread auto-join + `!preference` (Fletcher's `use_threads`).

Discord only shows a thread in your sidebar once you're a member of it, so
new threads in a busy server are easy to miss. Fletcher's fix: a per-user
`use_threads` preference, and whenever a new public thread appears the bot
adds every opted-in user to it. This is the same thing on this bot's
SQLite `user_prefs` table.

Commands (anyone, also from a DM):
  !preference use_threads true            join every new thread in this server
  !preference use_threads #chan, Events   only threads under those channels/categories
  !preference use_threads false           opt out
  !preference use_threads null            delete the row
  !preference use_threads                 show current value
  !preference <guild_id>:use_threads ...  set for one server from a DM
  /preference key value                   the same as a slash command

On behalf of someone else (owner or admin only):
  !preference @user use_threads true
  /preference key value user:@user

Any key is accepted; only `use_threads` is validated (Fletcher's KV store is
just as open). A guild row overrides a global (DM-set) row.

The summon itself is Fletcher's trick: `thread.add_user()` posts a visible
"X was added" system message per person, so instead the bot sends a silent
placeholder, edits the user mentions into it (edits never notify, mentions
add members), and deletes it. Membership survives the delete. Each thread is
summoned once; the `thread_summoned` table makes that survive restarts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord

import threadprefs as tp
from config import load_owner_username
from handler import Context

log = logging.getLogger("fletcher")

# Threads older than this with no summoned row predate the feature (or the
# DB); mark them and leave them alone rather than summoning into old threads.
STALE_AFTER = timedelta(minutes=5)
SUMMON_CHUNK = 50      # mentions per placeholder message
QUERY_CHUNK = 100      # guild.query_members cap


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("threads")
    if not cfg.get("enabled", True):
        log.info("threads module disabled in config")
        return

    client = ctx.client
    db = ctx.db
    h = ctx.handler
    q = ctx.quips
    owner = load_owner_username()
    # Users who get `use_threads = true` unless they say otherwise (Fletcher's
    # manual-mod-userslist, which defaults to the guild owner).
    default_on: set[int] = {int(x) for x in cfg.get("default_on", [])}
    locks: dict[int, asyncio.Lock] = {}

    q.add("preference", ["Noted 🫡", "Saved ✨", "Got it ^_^", "Written down 👀"])

    def _can_act_for_others(user: discord.User | discord.Member) -> bool:
        if owner and user.name == owner:
            return True
        return h.is_admin(user)

    # ---- preference get/set -------------------------------------------------

    async def _validate_use_threads(value: str, guild: discord.Guild | None) -> str | None:
        """Error text if a use_threads value names something the guild
        doesn't have, else None. Cache first; a REST refetch only when the
        cache says something is unknown (could be a typo or a stale cache)."""
        norm = tp.normalize(value)
        if isinstance(norm, bool) or guild is None:
            return None
        chan_ids = {c.id for c in guild.channels}
        cat_ids = {c.id for c in guild.categories}
        cat_names = {c.name.lower(): c.name for c in guild.categories}
        unknown = tp.unknown_targets(norm, chan_ids, cat_ids, cat_names)
        if not unknown:
            return None
        try:
            fetched = await guild.fetch_channels()
        except (discord.HTTPException, discord.Forbidden):
            log.warning("use_threads validation: fetch_channels failed for %s; allowing", guild.id)
            return None
        cats = [c for c in fetched if isinstance(c, discord.CategoryChannel)]
        chan_ids = {c.id for c in fetched}
        cat_ids = {c.id for c in cats}
        cat_names = {c.name.lower(): c.name for c in cats}
        unknown = tp.unknown_targets(unknown, chan_ids, cat_ids, cat_names)
        if not unknown:
            return None
        return tp.validation_message(unknown, cat_names, guild.name)

    def _wrap(text: str) -> str:
        if "```" in text:
            return text
        if len(text) > 120 or "\n" in text:
            return f"```{text}```"
        return f"`{text}`"

    async def apply_preference(
        *, actor: discord.User | discord.Member, target_id: int, raw_key: str,
        value: str | None, guild: discord.Guild | None,
    ) -> str:
        """Set, delete, or show one preference; returns the reply text."""
        guild_override, key = tp.parse_key(raw_key)
        if guild_override is not None:
            guild = client.get_guild(guild_override)
            gid = guild_override
        else:
            gid = guild.id if guild else 0
        if gid and gid not in ctx.config.guild_ids:
            return "I don't serve that server. >_<"
        on_behalf = target_id != actor.id
        if on_behalf and not _can_act_for_others(actor):
            return "Only the owner or an admin can set preferences for someone else."
        who = f"<@{target_id}>'s " if on_behalf else ""

        if value is None:
            current = db.get_pref(target_id, key, guild_id=gid)
            if tp.is_secret_key(key) and current is not None:
                return "`REDACTED`"
            if current is None:
                return f"{who}`{key}`: no value."
            return f"{who}`{key}` is set to: {_wrap(str(current))}"

        value = value.strip()[:tp.MAX_VALUE]
        if value.lower() == tp.DELETE_WORD:
            db.del_pref(target_id, key, guild_id=gid)
            return f"{who}`{key}` deleted"
        if key == "use_threads":
            err = await _validate_use_threads(value, guild)
            if err:
                return err
        db.set_pref(target_id, key, value, guild_id=gid)
        msg = f"{who}`{key}` set to {_wrap(value)}"
        if value.lower() in {"delete", "remove", "none", "nil"}:
            msg += (f'\n-# (that stored the literal string "{value}"; to delete, '
                    f"use `!preference {key} null`)")
        return q.tag(msg, "preference")

    @h.command(
        "!preference", "!pref",
        description=("Set or show a preference: `!preference use_threads true|false|#chan, Category`. "
                     "`!preference @user ...` sets it for someone else (owner/admin). "
                     "From a DM, `guild_id:key` targets one server."),
        min_args=1, dm=True,
    )
    async def preference_cmd(message: discord.Message, args: list[str], ctx: Context):  # noqa: ARG001
        target_id = message.author.id
        if len(args) >= 2:
            uid = tp.parse_user_mention(args[0])
            if uid is not None:
                target_id = uid
                args = args[1:]
        raw_key = args[0].replace("\\s", " ")
        value = " ".join(args[1:]) if len(args) > 1 else None
        reply = await apply_preference(
            actor=message.author, target_id=target_id, raw_key=raw_key,
            value=value, guild=message.guild,
        )
        await message.reply(reply, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())

    if ctx.tree is not None:
        from discord import app_commands

        @app_commands.command(name="preference", description="Set or show a preference (e.g. use_threads)")
        @app_commands.describe(
            key="Preference name, e.g. use_threads",
            value="New value (true/false, #channels or category names, or null to delete). Omit to show.",
            user="Set it for someone else (owner/admin only)",
        )
        async def preference_slash(interaction: discord.Interaction, key: str,
                                   value: str | None = None,
                                   user: discord.User | None = None):
            target = user.id if user else interaction.user.id
            reply = await apply_preference(
                actor=interaction.user, target_id=target, raw_key=key,
                value=value, guild=interaction.guild,
            )
            await interaction.response.send_message(
                reply, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        ctx.tree.add_command(preference_slash,
                             guilds=[discord.Object(id=g) for g in ctx.config.guild_ids])

    # ---- thread auto-join ---------------------------------------------------

    def _wants(user_id: int, guild_id: int, parent_id: int, category_id: int | None,
               category_name: str | None) -> bool:
        default = "true" if user_id in default_on else "false"
        raw = db.get_pref(user_id, "use_threads", default=default,
                          guild_id=guild_id, allow_global=True)
        return tp.matches(tp.normalize(str(raw)), parent_id, category_id, category_name)

    async def _category_name(thread: discord.Thread) -> str | None:
        parent = thread.parent
        if parent is None:
            return None
        if parent.category is not None:
            return parent.category.name
        # Cache miss: the category exists but wasn't replayed to us. One REST
        # call keeps name-based targets working.
        if parent.category_id:
            try:
                cat = await client.fetch_channel(parent.category_id)
                return getattr(cat, "name", None)
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                log.warning("threads: could not resolve category %s", parent.category_id)
        return None

    async def _summon(thread: discord.Thread, members: list[discord.Member]) -> None:
        try:
            for i in range(0, len(members), SUMMON_CHUNK):
                chunk = members[i:i + SUMMON_CHUNK]
                carrier = await thread.send("…", silent=True)
                await carrier.edit(content=" ".join(m.mention for m in chunk),
                                   allowed_mentions=discord.AllowedMentions(users=True))
                await carrier.delete()
        except discord.Forbidden:
            # No Send Messages here; fall back to the visible add.
            for m in members:
                try:
                    await thread.add_user(m)
                except discord.HTTPException:
                    log.warning("threads: could not add %s to %s", m, thread.id)

    async def thread_add(thread: discord.Thread, ctx: Context) -> None:  # noqa: ARG001
        lock = locks.setdefault(thread.id, asyncio.Lock())
        async with lock:
            try:
                await _thread_add(thread)
            finally:
                locks.pop(thread.id, None)

    async def _thread_add(thread: discord.Thread) -> None:
        guild = thread.guild
        if thread.is_private() or thread.parent is None:
            return
        if db.thread_summoned(thread.id):
            return
        if thread.created_at and datetime.now(timezone.utc) - thread.created_at > STALE_AFTER:
            db.mark_thread_summoned(thread.id, guild.id)
            return
        if not thread.me:
            me = guild.me or (client.user and guild.get_member(client.user.id))
            if me is not None:
                try:
                    await thread.add_user(me)
                except discord.HTTPException:
                    log.warning("threads: could not join %s myself", thread.id)

        # Who is already there (members list is lazy; fetch it).
        seen: set[int] = set()
        try:
            seen.update(m.id for m in await thread.fetch_members())
        except discord.HTTPException:
            seen.update(m.id for m in thread.members)
        if thread.owner_id:
            seen.add(thread.owner_id)
        if client.user:
            seen.add(client.user.id)

        parent = thread.parent
        category_id = parent.category_id
        category_name = await _category_name(thread)

        candidate_ids = [uid for uid in set(db.users_with_pref("use_threads", guild.id)) | default_on
                         if uid not in seen]
        if not candidate_ids:
            db.mark_thread_summoned(thread.id, guild.id)
            return

        # The member cache drops people; ask the gateway for the exact ids.
        members: list[discord.Member] = []
        for i in range(0, len(candidate_ids), QUERY_CHUNK):
            try:
                members.extend(await guild.query_members(
                    user_ids=candidate_ids[i:i + QUERY_CHUNK], cache=True))
            except (discord.HTTPException, asyncio.TimeoutError):
                log.warning("threads: query_members failed for guild %s", guild.id)

        to_add = [
            m for m in members
            if m.id not in seen
            and parent.permissions_for(m).read_messages
            and _wants(m.id, guild.id, parent.id, category_id, category_name)
        ]
        if to_add:
            log.info("threads: summoning %d user(s) into %s (%s)", len(to_add), thread.name, thread.id)
            await _summon(thread, to_add)
        db.mark_thread_summoned(thread.id, guild.id)

    h.thread_handlers.append(thread_add)
    log.info("threads ready -- !preference use_threads + auto-join on new threads")
