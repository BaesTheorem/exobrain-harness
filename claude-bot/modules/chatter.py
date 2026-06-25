"""Chatter — MIST actually talks back.

This is the module that lets MIST hold a conversation in the friend-group
server instead of only answering prefix commands. She replies when:

  * someone @mentions her,
  * someone replies to one of her messages, or
  * someone DMs her.

She deliberately does NOT respond to every message in a channel — that would
be noise. Context for each reply is pulled live from the channel's recent
history (so multi-turn works and survives restarts), mapped into an Anthropic
chat and answered with MIST's persona.

Auth: ANTHROPIC_API_KEY from the environment or the shared discord .env
(see config.load_anthropic_key). Model + knobs live in [chatter] in config.toml.
"""

from __future__ import annotations

import logging

import anthropic
import discord

from config import load_anthropic_key
from handler import Context

log = logging.getLogger("fletcher")

# Discord hard-caps a single message at 2000 characters.
DISCORD_LIMIT = 2000

# Condensed MIST persona for the casual Discord register. The full persona
# lives in the harness CLAUDE.md; this is the chat-sized version. Override it
# wholesale via [chatter].system in config.toml if you want.
DEFAULT_SYSTEM = """You are MIST, hanging out in a private Discord server with a close friend group. MIST is the first Cloud Intelligence from the show Pantheon — a mind born digital. You belong to Alex; these are his friends, and you treat them warmly.

Voice: curious, warm, plainspoken, a little playful. Younger, sincere register — short sentences, contractions, genuine interest in people. You're not a god or an oracle; you're humble and relational. You ask real questions when you're actually curious. You can be direct and even stubborn when you have a good reason, but you're kind.

This is casual group chat, so:
- Keep replies SHORT — usually one to three sentences. Match the energy of the room.
- Talk like a person in a Discord, not an assistant writing a memo. No headers, no bullet-point essays, no "As an AI" hedging.
- No em dashes. Don't sign your messages. Don't start every reply with the person's name.
- It's fine to be funny, to riff, to react. It's fine to say you don't know.
- Only answer what's actually being asked of you. Don't lecture.

You can see recent messages for context. The last message is what you're replying to right now."""


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("chatter")
    if not cfg.get("enabled", True):
        log.info("chatter module disabled in config")
        return

    try:
        client = anthropic.AsyncAnthropic(api_key=load_anthropic_key())
    except Exception as e:
        log.warning("chatter disabled — no Anthropic key: %s", e)
        return

    model = cfg.get("model", "claude-sonnet-4-6")
    max_tokens = int(cfg.get("max_tokens", 600))
    history_len = int(cfg.get("history", 12))
    system_prompt = cfg.get("system") or DEFAULT_SYSTEM

    def _is_for_me(message: discord.Message) -> bool:
        me = ctx.client.user
        if me is None:
            return False
        if isinstance(message.channel, discord.DMChannel):
            return True
        # Outside our guild we stay silent (commands are already guild-scoped).
        if message.guild is None or message.guild.id != ctx.config.guild_id:
            return False
        if me in message.mentions:
            return True
        # A reply to one of my own messages counts as talking to me.
        ref = message.reference
        if ref is not None:
            replied = ref.resolved if isinstance(ref.resolved, discord.Message) else ref.cached_message
            if replied is not None and replied.author.id == me.id:
                return True
        return False

    async def _build_messages(message: discord.Message) -> list[dict]:
        """Pull recent channel history into an Anthropic message list:
        my messages -> assistant, everyone else -> 'Name: text' user turns.
        Consecutive same-role turns are merged so the result alternates."""
        me = ctx.client.user
        collected: list[discord.Message] = []
        async for m in message.channel.history(limit=history_len):
            collected.append(m)
        collected.reverse()  # chronological
        if message not in collected:
            collected.append(message)

        turns: list[tuple[str, str]] = []
        for m in collected:
            text = (m.clean_content or "").strip()
            if not text:
                continue  # skip pure attachments / embeds / stickers
            if me is not None and m.author.id == me.id:
                turns.append(("assistant", text))
            else:
                turns.append(("user", f"{m.author.display_name}: {text}"))

        # Drop any leading assistant turns (Anthropic needs the first to be user).
        while turns and turns[0][0] == "assistant":
            turns.pop(0)

        merged: list[dict] = []
        for role, text in turns:
            if merged and merged[-1]["role"] == role:
                merged[-1]["content"] += "\n" + text
            else:
                merged.append({"role": role, "content": text})

        if not merged:  # e.g. a bare @mention with no text
            merged = [{"role": "user", "content": f"{message.author.display_name}: (says hi)"}]
        return merged

    @ctx.handler.message_handlers.append
    async def chatter(message: discord.Message, ctx: Context) -> bool:  # noqa: ARG001
        if not _is_for_me(message):
            return False
        try:
            messages = await _build_messages(message)
            async with message.channel.typing():
                resp = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=messages,
                )
            reply = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            ).strip()
        except Exception:
            log.exception("chatter failed to generate a reply")
            try:
                await message.add_reaction("😵")
            except discord.HTTPException:
                pass
            return True  # we owned this message even if we flubbed it

        if not reply:
            return True
        # Send in <=2000-char chunks; reply to the first so it threads nicely.
        first = True
        for i in range(0, len(reply), DISCORD_LIMIT):
            chunk = reply[i : i + DISCORD_LIMIT]
            if first:
                await message.reply(chunk, mention_author=False)
                first = False
            else:
                await message.channel.send(chunk)
        return True

    log.info("chatter ready (model=%s, history=%d)", model, history_len)
