"""Google Photos video embedder -- post a Google Photos share link and MIST
replies with a version that plays inline.

Discord's native unfurl of a Google Photos link is a static thumbnail. The
gphotos-embed Cloudflare Worker (github.com/BaesTheorem/gphotos-embed) serves
the same share path with og:video tags pointing at a streamable mp4, so
swapping the host is enough for Discord to render a player.

Unlike the Instagram module this runs automatically on every message: any
Google Photos link in a served guild (or a DM) is probed through the worker,
and only links that turn out to be videos get a reply. Photos and albums are
left alone, since Discord already previews those. Links wrapped in <angle
brackets> are skipped, because that's how someone says "don't embed this".

The handler never consumes the message (always returns False), so a message
that also @mentions MIST still reaches chatter. The probe and reply run in a
background task so they don't delay anything else.

Discord crawls a link once, immediately after the post, and keeps a failed
result for that URL. On a cold video (Google's transcode not warm, the worker's
cache empty) a long clip loads too slowly for that one crawl, and the reply
shows no embed at all (a 40 MB pitch video on 2026-10-23). So after the reply,
the module checks for a video embed. If there is none, it downloads the video
through the worker to warm it, then edits the reply with a new query string so
Discord crawls it again.
"""

from __future__ import annotations

import asyncio
import logging
import re

import aiohttp
import discord

from handler import Context

log = logging.getLogger("fletcher")

_GPHOTOS_RE = re.compile(
    r"(?<!<)https?://(photos\.app\.goo\.gl|photos\.google\.com)(/[^\s<>|]+)",
    re.IGNORECASE,
)
_MAX_LINKS = 3
# Strong refs to in-flight tasks; asyncio only keeps weak ones.
_tasks: set[asyncio.Task] = set()
_BOT_UA = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
_OG_VIDEO_RE = re.compile(r'<meta property="og:video" content="([^"]+)"')
# Seconds to wait for Discord's unfurl before each check, and the retries after it.
_EMBED_WAIT = 12
_RETRIES = 2


def find_links(text: str) -> list[tuple[str, str]]:
    """(host, path) pairs for Google Photos share links, deduped, in order."""
    out: list[tuple[str, str]] = []
    for m in _GPHOTOS_RE.finditer(text or ""):
        path = m.group(2).rstrip(".,;:!?)]*_~'\"")
        if m.group(1).lower() == "photos.google.com" and not path.startswith("/share/"):
            continue
        pair = (m.group(1).lower(), path)
        if pair not in out:
            out.append(pair)
    return out[:_MAX_LINKS]


def to_embed_url(path: str, host: str) -> str:
    """Both link shapes map onto the worker by path: /share/... stays as-is and
    a goo.gl short code becomes /<code>."""
    return f"https://{host}{path}"


def with_retry_param(url: str, n: int) -> str:
    """A different URL for the same video, so Discord ignores its cached failure.
    The worker drops the query on short links and Google ignores extra params."""
    return f"{url}{'&' if '?' in url else '?'}r={n}"


async def video_url(url: str, session: aiohttp.ClientSession) -> str | None:
    """Ask the worker as Discord's crawler would; it only emits og:video for videos.
    Returns the og:video mp4 URL, or None for a photo, an album or a failure."""
    try:
        async with session.get(url, headers={"User-Agent": _BOT_UA}, allow_redirects=False) as resp:
            if resp.status != 200:
                return None
            m = _OG_VIDEO_RE.search(await resp.text())
            return m.group(1).replace("&amp;", "&") if m else None
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.debug("gphotos probe failed for %s: %s", url, e)
        return None


async def warm(mp4: str, session: aiohttp.ClientSession) -> None:
    """Download the video through the worker and discard it, so Google's
    transcode and Cloudflare's cache are warm when Discord crawls again."""
    try:
        async with session.get(mp4, headers={"User-Agent": _BOT_UA},
                               timeout=aiohttp.ClientTimeout(total=120)) as resp:
            async for _ in resp.content.iter_chunked(1 << 20):
                pass
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.debug("gphotos warm failed for %s: %s", mp4, e)


def video_embed_count(msg: discord.Message) -> int:
    return sum(1 for e in msg.embeds if e.type == "video" or e.video)


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("gphotos")
    if not cfg.get("enabled", True):
        log.info("gphotos module disabled in config")
        return
    host = cfg.get("host", "gphotos.alex-hedtke.workers.dev")
    suppress_original = bool(cfg.get("suppress_original", True))
    timeout = aiohttp.ClientTimeout(total=20)

    async def reply_with_embeds(message: discord.Message, links: list[tuple[str, str]]) -> None:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            urls = [to_embed_url(path, host) for _, path in links]
            mp4s = await asyncio.gather(*(video_url(u, session) for u in urls))
            videos = [(u, v) for u, v in zip(urls, mp4s, strict=True) if v]
            if not videos:
                return
            log.info("gphotos: embedding %d video(s) for %s", len(videos), message.author)
            reply = await message.reply("\n".join(u for u, _ in videos), mention_author=False)
            # Hide the original's static thumbnail so the video isn't doubled up.
            # Needs Manage Messages; without it the original preview just stays.
            if suppress_original and message.guild is not None:
                try:
                    await message.edit(suppress=True)
                except discord.HTTPException:
                    pass
            await ensure_embedded(reply, videos, session)

    async def ensure_embedded(reply: discord.Message, videos: list[tuple[str, str]],
                              session: aiohttp.ClientSession) -> None:
        for attempt in range(1, _RETRIES + 1):
            await asyncio.sleep(_EMBED_WAIT)
            try:
                reply = await reply.channel.fetch_message(reply.id)
            except discord.HTTPException:
                return
            if video_embed_count(reply) >= len(videos):
                return
            log.info("gphotos: no video embed on %s, warming and retry %d", reply.id, attempt)
            await asyncio.gather(*(warm(v, session) for _, v in videos))
            content = "\n".join(with_retry_param(u, attempt) for u, _ in videos)
            try:
                reply = await reply.edit(content=content)
            except discord.HTTPException:
                return
        log.warning("gphotos: video embed still missing on %s after %d retries", reply.id, _RETRIES)

    async def embed_gphotos(message: discord.Message, ctx: Context) -> bool:
        if message.guild is not None and message.guild.id not in ctx.config.guild_ids:
            return False
        text = message.content or ""
        snaps = getattr(message, "message_snapshots", None)
        if snaps:
            text = " ".join([text] + [getattr(s, "content", "") or "" for s in snaps])
        links = find_links(text)
        if links:
            task = asyncio.create_task(reply_with_embeds(message, links))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
            task.add_done_callback(_log_failure)
        return False

    # Front of the chain so it sees every message before chatter can claim it.
    ctx.handler.message_handlers.insert(0, embed_gphotos)
    log.info("gphotos video embedder ready -- host=%s", host)


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("gphotos embed failed", exc_info=task.exception())
