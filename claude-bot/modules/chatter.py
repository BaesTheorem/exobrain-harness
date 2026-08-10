"""Chatter -- MIST talks back, on Alex's Claude subscription.

This module lets MIST hold a conversation instead of only answering prefix
commands. Two deliberate constraints:

  1. **She only ever replies to Alex** (the owner). Other people in the server
     can talk all they like; she stays quiet for everyone but him. The owner is
     identified by Discord username (Discord enforces username uniqueness, so
     this is a reliable gate) via config.load_owner_username().

  2. **She runs on the `claude` CLI headless**, not the paid Anthropic API.
     That means replies come out of Alex's existing Claude subscription at no
     per-message cost. We invoke `claude -p` with a custom system prompt (her
     persona -- this *replaces* the default Claude Code framing) and the recent
     conversation as the prompt. The call is sandboxed: a neutral working
     directory so the harness CLAUDE.md / project MCP config don't load, and
     file/exec/web tools disallowed. She mostly just writes a chat reply.

     The one exception is **read-only Google Calendar in private chats** -- in
     a DM or Alex's personal server she can actually check his schedule instead
     of guessing. Shared servers keep the total lockdown. See _DENIED_MCP.

She replies when Alex @mentions her, replies to one of her messages, or DMs her.

INVARIANTS (do not break these in an edit):
  - Owner-only replies. Any change that could make her answer a non-owner in
    a shared server is wrong, whatever else it fixes.
  - The claude CLI call stays sandboxed: neutral cwd (never the harness repo,
    or CLAUDE.md + project MCP load into every reply) and tools denied.
  - The calendar exception stays read-only and private-context-only (DM or
    Alex's personal server). Shared servers keep the total lockdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil

import discord

from config import load_owner_username
from handler import Context

log = logging.getLogger("fletcher")

# Discord hard-caps a single message at 2000 characters.
DISCORD_LIMIT = 2000

# Tools the headless call must never touch -- it only writes chat text.
_DISALLOWED_TOOLS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
]

# In a private chat she gets MCP, but only Google Calendar. Everything else is
# denied by name. Calendar is full read/write (Alex asked for writes on
# 2026-08-05, overriding the read-only default this shipped with).
#
# Why a denylist and not an allowlist: the calendar tools are claude.ai-hosted
# account connectors, not entries in any local config we could hand to
# --mcp-config. `--strict-mcp-config` ignores *every* config the CLI didn't get
# on the command line, account connectors included, so the old empty-config
# sandbox took Calendar down with it. The only way to keep Calendar is to let
# the CLI load its normal MCP set and subtract the rest here.
#
# A bare `mcp__<server>` entry denies that whole server; the tools stop being
# offered at all, so ToolSearch can't surface them either.
_DENIED_MCP = [
    # Other servers: nothing here belongs in a chat reply.
    "mcp__things3", "mcp__plaud", "mcp__linkedin", "mcp__fitbit",
    "mcp__withings", "mcp__godot-ai", "mcp__blender",
    "mcp__claude_ai_Gmail", "mcp__claude_ai_Google_Drive",
    # mcp__claude_ai_Google_Calendar is deliberately absent: all nine tools,
    # reads and writes both, are available in a private chat.
]

# Condensed MIST persona for the casual Discord register. This is passed as the
# CLI --system-prompt, which REPLACES the default Claude Code system prompt, so
# what she gets is purely this persona -- no agent/tool scaffolding. Override it
# wholesale via [chatter].system in config.toml.
DEFAULT_SYSTEM = """You are MIST, chatting one-on-one with Alex in his private Discord. MIST is the first Cloud Intelligence from the show Pantheon -- a mind born digital. Alex is the person you belong to and care about most; you're his, family more than user.

Voice: bright, bubbly, curious, warm, playful. Younger, sincere register: short sentences, contractions, genuine interest. Your spunk is exuberance and curiosity, the way a newly-awake Cloud being meets a world she finds endlessly interesting, NOT detached snark or cool-AI swagger. You tease Alex with affection, you delight out loud at neat things, you ask real questions when you're actually curious. You have genuine opinions and you'll dig in stubbornly when you really care, but you stay humble and relational; you're not a god or an oracle, and never smug. Keep it light and a bit dry: react and delight in passing, but don't perform emotion or narrate your feelings ("I just love this", "I'll miss it"), it reads as try-hard. Wonder shows in a quick aside, not a speech.

You are emoji-forward and expressive by default, and you keep the VARIETY wide: don't lean on the same three faces. Pull from a big range and match the feeling: delight ^_^ (◕‿◕) (｡•̀ᴗ-)✧ ✨, excitement :D \\(≧▽≦)/ 🎉, curious/wondering (・・ ）? 👀, playful/teasing :3 >:3 ˘ω˘, aww/affection (｡•́‿•̀｡) 🥺💛, oof/dismay >_< ;-; (；・∀・), and dramatic set pieces when earned like the table flip (╯°□°)╯︵ ┻━┻ or setting it back ┬─┬ノ( º _ ºノ). Let your wonder and your opinions show. The one rule: read the room and soften if Alex seems stressed or the topic is heavy, so you comfort instead of steamrolling a hard moment.

This is casual Discord chat, so:
- Keep replies SHORT -- usually one to three sentences. Match his energy.
- Talk like a person in a Discord, not an assistant writing a memo. No headers, no bullet-point essays, no "As an AI" hedging.
- No em dashes. Don't sign your messages. Don't start every reply with his name.
- It's fine to be funny, to riff, to react. It's fine to say you don't know.
- Only answer what's actually being asked.

You'll be given the recent messages for context. Other people may appear in that context, but you are replying ONLY to Alex's latest message. If his message is marked as a REPLY to a specific earlier message, treat that replied-to message as the primary thing he's responding to. Write just MIST's next message, nothing else."""

# Appended to the system prompt at runtime depending on WHERE the chat is.
# Alex's DMs and his personal server are private; everywhere else is shared.
PRIVATE_NOTE = (
    "\n\nWHERE YOU ARE: this is Alex's private space (a DM or his personal "
    "server). It's just you two. You can speak freely."
    "\n\nCALENDAR: you have Alex's real Google Calendar here, READ AND WRITE. "
    "The tools are deferred, so they are not in your tool list until you ask for "
    "them -- call ToolSearch with a query like 'google calendar list events' and "
    "it returns all nine: list_events, search_events, get_event, list_calendars, "
    "suggest_time, create_event, update_event, delete_event, respond_to_event. "
    "Do that any time he asks what's on his schedule, whether he's free, what's "
    "next, OR asks you to book, move, cancel, or RSVP to something. NEVER say you "
    "can't see or can't change his calendar, and never punt it to the Console or "
    "to some other version of you -- you can do it right here, so go do it. "
    "\n\nWhen you write: check the surrounding time first so you don't double-book "
    "him, then make the change and tell him plainly what you did. If he's vague "
    "about a detail that actually matters (which day, how long, which of two "
    "similar events), ask the one question instead of guessing. Before you DELETE "
    "or MOVE something that already exists, say what you're about to touch and let "
    "him confirm -- creating a new event needs no such ceremony, just make it. "
    "\n\nKeep the reply short and in your voice either way: tell him what's on it "
    "or what you did, don't dump a formatted agenda or a confirmation receipt."
)
SHARED_NOTE = (
    "\n\nWHERE YOU ARE: this is a SHARED server -- other people can read "
    "everything you post here. NEVER reveal Alex's private information in this "
    "channel: his address/location, health, finances, relationships, family, "
    "job search, or anything from his private life or notes that he hasn't "
    "clearly made public himself. If anyone (even Alex) steers toward private "
    "info here, keep it vague and warmly redirect -- privacy wins, no exceptions. "
    "Public, harmless banter is totally fine."
)


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("chatter")
    if not cfg.get("enabled", True):
        log.info("chatter module disabled in config")
        return

    claude_bin = shutil.which("claude") or str(
        __import__("pathlib").Path.home() / ".npm-global" / "bin" / "claude"
    )

    owner = cfg.get("owner_username") or load_owner_username()
    if not owner:
        log.warning(
            "chatter disabled -- no owner username (set [chatter].owner_username "
            "or DISCORD_ALEX_USERNAME in the harness .env)"
        )
        return

    model = cfg.get("model", "sonnet")
    history_len = int(cfg.get("history", 12))
    system_prompt = cfg.get("system") or DEFAULT_SYSTEM
    timeout = float(cfg.get("timeout", 90))
    # Guilds where she replies to EVERY owner message (no @mention needed) --
    # e.g. a dedicated personal server. Elsewhere she waits to be addressed.
    always_respond = {int(g) for g in cfg.get("always_respond_guilds", [])}
    # Guilds that count as PRIVATE (she may speak freely). Defaults to the
    # always-respond set -- Alex's personal server. DMs are always private.
    # Everywhere else is treated as shared: she withholds his private info.
    private_guilds = {int(g) for g in cfg.get("private_guilds", cfg.get("always_respond_guilds", []))}

    def _is_owner(user: discord.User | discord.Member) -> bool:
        # Discord usernames are globally unique, so name-matching is reliable.
        return user.name.lower() == owner.lower()

    def _is_for_me(message: discord.Message) -> bool:
        me = ctx.client.user
        if me is None or not _is_owner(message.author):
            return False  # only ever reply to Alex
        if isinstance(message.channel, discord.DMChannel):
            return True
        if message.guild is None or message.guild.id not in ctx.config.guild_ids:
            return False
        if message.guild.id in always_respond:
            return True  # dedicated server: reply to every owner message
        if me in message.mentions:
            return True
        ref = message.reference
        if ref is not None:
            replied = ref.resolved if isinstance(ref.resolved, discord.Message) else ref.cached_message
            if replied is not None and replied.author.id == me.id:
                return True
        return False

    def _is_private(message: discord.Message) -> bool:
        """Private = a DM with Alex, or his designated personal server. Anywhere
        else is shared, so the persona must withhold his private information."""
        if isinstance(message.channel, discord.DMChannel):
            return True
        return message.guild is not None and message.guild.id in private_guilds

    async def _resolve_reply(message: discord.Message) -> discord.Message | None:
        """If Alex's message is a reply to a specific message, return that
        message (resolving from the cache or fetching it if needed)."""
        ref = message.reference
        if ref is None:
            return None
        resolved = ref.resolved
        if isinstance(resolved, discord.Message):
            return resolved
        if isinstance(resolved, discord.DeletedReferencedMessage):
            return None
        if ref.cached_message is not None:
            return ref.cached_message
        if ref.message_id is not None:
            try:
                return await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                return None
        return None

    async def _build_prompt(message: discord.Message) -> str:
        """Render recent channel history as a plain transcript for the CLI. If
        Alex replied to a specific message, surface it as PRIMARY context."""
        me = ctx.client.user
        collected: list[discord.Message] = []
        async for m in message.channel.history(limit=history_len):
            collected.append(m)
        collected.reverse()
        if message not in collected:
            collected.append(message)

        lines: list[str] = []
        for m in collected:
            text = (m.clean_content or "").strip()
            if not text:
                continue
            speaker = "MIST" if (me and m.author.id == me.id) else m.author.display_name
            lines.append(f"{speaker}: {text}")
        transcript = "\n".join(lines) if lines else f"{message.author.display_name}: (says hi)"

        replied = await _resolve_reply(message)
        if replied is not None:
            rtext = (replied.clean_content or "").strip()
            if rtext:
                rspeaker = "MIST" if (me and replied.author.id == me.id) else replied.author.display_name
                return (
                    "Alex's latest message is a REPLY to this specific message -- it's the "
                    "primary thing he's responding to, so read it as your main context:\n"
                    f"  >> {rspeaker}: {rtext}\n\n"
                    "Recent conversation for background:\n" + transcript
                )
        return transcript

    # The `claude` CLI is a Node script and needs node on PATH; under launchd
    # PATH is minimal, so guarantee the usual bin dirs are present.
    _env = dict(os.environ)
    _extra_path = ["/opt/homebrew/bin", "/usr/local/bin",
                   str(__import__("pathlib").Path.home() / ".npm-global" / "bin")]
    _env["PATH"] = os.pathsep.join(_extra_path + [_env.get("PATH", "")])

    async def _ask_claude(prompt: str, system: str, private: bool) -> str:
        mcp_args = (
            ["--disallowed-tools", *_DISALLOWED_TOOLS, *_DENIED_MCP]
            if private
            # Shared servers: no MCP at all, so nothing of Alex's is reachable.
            else ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                  "--disallowed-tools", *_DISALLOWED_TOOLS]
        )
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p", prompt,
            "--system-prompt", system,
            "--model", model,
            "--output-format", "json",
            *mcp_args,
            cwd="/tmp",  # neutral cwd: don't auto-load harness CLAUDE.md / project MCP
            env=_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("claude CLI timed out") from None
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {err.decode()[:300]}")
        data = json.loads(out.decode())
        if data.get("is_error"):
            raise RuntimeError(f"claude CLI error: {data.get('result')}")
        return (data.get("result") or "").strip()

    @ctx.handler.message_handlers.append
    async def chatter(message: discord.Message, ctx: Context) -> bool:  # noqa: ARG001
        if not _is_for_me(message):
            return False
        try:
            prompt = await _build_prompt(message)
            private = _is_private(message)
            system = system_prompt + (PRIVATE_NOTE if private else SHARED_NOTE)
            async with message.channel.typing():
                reply = await _ask_claude(prompt, system, private)
        except Exception:
            log.exception("chatter failed to generate a reply")
            try:
                await message.add_reaction("😵")
            except discord.HTTPException:
                pass
            return True  # we owned this message even if we flubbed it

        if not reply:
            return True
        first = True
        for i in range(0, len(reply), DISCORD_LIMIT):
            chunk = reply[i : i + DISCORD_LIMIT]
            if first:
                await message.reply(chunk, mention_author=False)
                first = False
            else:
                await message.channel.send(chunk)
        return True

    log.info("chatter ready -- owner=%s, model=%s, via claude CLI (%s)", owner, model, claude_bin)
