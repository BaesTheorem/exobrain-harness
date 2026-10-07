"""Clippy -- per-person rate triggers with a semantic check (see watches.py).

Counts every message a watched user posts in a served server, per channel.
When the count inside the window reaches the rule's threshold, their messages
from that window go to a sandboxed model call that answers the rule's yes/no
question; on YES, MIST replies to their latest message with the rule's text
(plus the person's standing append line, if any). The reply is in-channel,
never a DM.

Runs first in the message_handlers chain and never consumes a message, so
chatter and the others still see it. The model call runs as a task, so a
slow verdict never delays the rest of the bot.

INVARIANTS (do not break these in an edit):
  - Every model call here is the sandbox (models.SANDBOX_ARGS), on the guest
    model, with the window text framed by security/bin/mist-frame. The
    verdict's first word is the only thing acted on.
  - Only a watched login username triggers it; a display name never does.
  - The handler returns False always.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import discord

import staged
import watches
from handler import Context
from models import SANDBOX_ARGS, find_claude_bin

log = logging.getLogger("fletcher")

HARNESS_ROOT = Path(__file__).resolve().parents[2]
FRAME = HARNESS_ROOT / "security" / "bin" / "mist-frame"
DISCORD_LIMIT = 2000


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("clippy")
    if not cfg.get("enabled", True):
        log.info("clippy module disabled in config")
        return
    chatter_cfg = ctx.config.section("chatter")
    model = cfg.get("model") or chatter_cfg.get("guest_model", "claude-fable-5-1")
    timeout = float(cfg.get("timeout", 90))
    claude_bin = find_claude_bin() or str(Path.home() / ".local" / "bin" / "claude")

    window = watches.Window()
    state = watches.FireState()

    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin",
                                   str(Path.home() / ".local" / "bin"),
                                   str(Path.home() / ".npm-global" / "bin"), env.get("PATH", "")])

    async def _frame(text: str, source: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            str(FRAME), "--source", source,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate(text.encode())
        return out.decode()

    async def _verdict(prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            claude_bin, "-p", prompt, "--system-prompt", watches.CLASSIFIER_SYSTEM,
            "--output-format", "json", "--model", model, *SANDBOX_ARGS,
            cwd="/tmp", env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"classifier timed out after {int(timeout)}s") from None
        if proc.returncode != 0:
            raise RuntimeError(f"classifier exited {proc.returncode}: {err.decode()[:200]}")
        data = json.loads(out.decode())
        if data.get("is_error"):
            raise RuntimeError(f"classifier error: {data.get('result')}")
        return (data.get("result") or "").strip()

    async def _window_text(message: discord.Message, window_s: float) -> str:
        """The watched user's own messages in this channel inside the window."""
        cutoff = time.time() - window_s
        lines: list[str] = []
        async for m in message.channel.history(limit=60):
            if m.created_at.timestamp() < cutoff:
                break
            if m.author.id == message.author.id and (m.clean_content or "").strip():
                lines.append(m.clean_content.strip())
        lines.reverse()
        return "\n\n".join(lines)

    async def _check_and_reply(message: discord.Message, rule: dict, key: tuple) -> None:
        chan = getattr(message.channel, "name", "?")
        try:
            text = await _window_text(message, float(rule["window_min"]) * 60)
            if not text:
                return
            framed = await _frame(text, f"discord #{chan}, one author")
            verdict = await _verdict(watches.classifier_prompt(rule["ask"], framed))
        except Exception:
            log.exception("clippy: check failed in #%s", chan)
            return
        log.info("clippy: #%s verdict for %s: %s", chan, message.author.name, verdict.splitlines()[0] if verdict else "?")
        if not watches.is_yes(verdict):
            return
        reply = staged.with_append(rule["say"], message.author.name)
        try:
            await message.reply(reply[:DISCORD_LIMIT], mention_author=False)
        except discord.HTTPException:
            log.exception("clippy: reply failed in #%s", chan)
            return
        state.fired(key, time.time())
        window.clear(key)

    async def on_message(message: discord.Message, ctx: Context) -> bool:  # noqa: ARG001
        if message.author.bot or message.guild is None or message.guild.id not in ctx.config.guild_ids:
            return False
        chan_name = getattr(message.channel, "name", None)
        rule = watches.rule_for(message.author.name, chan_name)
        if rule is None:
            return False
        key = (message.author.id, message.channel.id)
        now = time.time()
        n = window.add(key, now, float(rule["window_min"]) * 60)
        if state.may_check(key, n, rule, now):
            asyncio.create_task(_check_and_reply(message, rule, key))
        return False

    # The prefix command, for anyone, self-only: the same parser the chat path
    # uses when MIST emits a !watch line for the person speaking.
    @ctx.handler.command(*watches.COMMAND_TRIGGERS, description=(
        'self-only pattern nudge: !watch 5/30m ask "yes/no question about your messages" '
        'say "text" [cooldown 30m] [in #channel] · !watch off · !watch'))
    async def watch_cmd(message: discord.Message, args: list[str], ctx: Context) -> None:  # noqa: ARG001
        try:
            cmd = watches.parse_command(message.content)
            note = watches.apply_command(message.author.name, cmd)
        except ValueError as exc:
            note = str(exc)
        await message.reply(note[:DISCORD_LIMIT], mention_author=False)

    ctx.handler.message_handlers.insert(0, on_message)
    log.info("clippy ready -- %d watch(es), classifier on %s", len(watches.load()), model)
