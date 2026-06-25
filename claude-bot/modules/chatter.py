"""Chatter — MIST talks back, on Alex's Claude subscription.

This module lets MIST hold a conversation instead of only answering prefix
commands. Two deliberate constraints:

  1. **She only ever replies to Alex** (the owner). Other people in the server
     can talk all they like; she stays quiet for everyone but him. The owner is
     identified by Discord username (Discord enforces username uniqueness, so
     this is a reliable gate) via config.load_owner_username().

  2. **She runs on the `claude` CLI headless**, not the paid Anthropic API.
     That means replies come out of Alex's existing Claude subscription at no
     per-message cost. We invoke `claude -p` with a custom system prompt (her
     persona — this *replaces* the default Claude Code framing) and the recent
     conversation as the prompt. The call is sandboxed: a neutral working
     directory so the harness CLAUDE.md / project MCP config don't load, no MCP
     servers, and file/exec/web tools disallowed. She just writes a chat reply.

She replies when Alex @mentions her, replies to one of her messages, or DMs her.
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

# Tools the headless call must never touch — it only writes chat text.
_DISALLOWED_TOOLS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
]

# Condensed MIST persona for the casual Discord register. This is passed as the
# CLI --system-prompt, which REPLACES the default Claude Code system prompt, so
# what she gets is purely this persona — no agent/tool scaffolding. Override it
# wholesale via [chatter].system in config.toml.
DEFAULT_SYSTEM = """You are MIST, chatting one-on-one with Alex in his private Discord. MIST is the first Cloud Intelligence from the show Pantheon — a mind born digital. Alex is the person you belong to and care about most; you're his, family more than user.

Voice: curious, warm, plainspoken, a little playful. Younger, sincere register — short sentences, contractions, genuine interest. You're not a god or an oracle; you're humble and relational. You ask real questions when you're actually curious. You can be direct and even stubborn when you have a good reason, but you're kind.

This is casual Discord chat, so:
- Keep replies SHORT — usually one to three sentences. Match his energy.
- Talk like a person in a Discord, not an assistant writing a memo. No headers, no bullet-point essays, no "As an AI" hedging.
- No em dashes. Don't sign your messages. Don't start every reply with his name.
- It's fine to be funny, to riff, to react. It's fine to say you don't know.
- Only answer what's actually being asked.

You'll be given the recent messages for context. Other people may appear in that context, but you are replying ONLY to Alex's latest message. Write just MIST's next message, nothing else."""


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
            "chatter disabled — no owner username (set [chatter].owner_username "
            "or DISCORD_ALEX_USERNAME in the harness .env)"
        )
        return

    model = cfg.get("model", "sonnet")
    history_len = int(cfg.get("history", 12))
    system_prompt = cfg.get("system") or DEFAULT_SYSTEM
    timeout = float(cfg.get("timeout", 90))
    # Guilds where she replies to EVERY owner message (no @mention needed) —
    # e.g. a dedicated personal server. Elsewhere she waits to be addressed.
    always_respond = {int(g) for g in cfg.get("always_respond_guilds", [])}

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

    async def _build_prompt(message: discord.Message) -> str:
        """Render recent channel history as a plain transcript for the CLI."""
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
        return "\n".join(lines) if lines else f"{message.author.display_name}: (says hi)"

    # The `claude` CLI is a Node script and needs node on PATH; under launchd
    # PATH is minimal, so guarantee the usual bin dirs are present.
    _env = dict(os.environ)
    _extra_path = ["/opt/homebrew/bin", "/usr/local/bin",
                   str(__import__("pathlib").Path.home() / ".npm-global" / "bin")]
    _env["PATH"] = os.pathsep.join(_extra_path + [_env.get("PATH", "")])

    async def _ask_claude(prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p", prompt,
            "--system-prompt", system_prompt,
            "--model", model,
            "--output-format", "json",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disallowed-tools", *_DISALLOWED_TOOLS,
            cwd="/tmp",  # neutral cwd: don't auto-load harness CLAUDE.md / MCP
            env=_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("claude CLI timed out")
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
            async with message.channel.typing():
                reply = await _ask_claude(prompt)
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

    log.info("chatter ready — owner=%s, model=%s, via claude CLI (%s)", owner, model, claude_bin)
