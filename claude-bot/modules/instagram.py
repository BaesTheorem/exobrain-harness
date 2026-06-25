"""Instagram reel embedder — tag MIST in a reply to an Instagram post and she
reposts it so the reel plays inline as a video.

Discord's native Instagram unfurl is broken: it shows a static thumbnail (or
nothing), never the video. Fletcher's fix is to rewrite the link through an
embed-fixer frontend — `kkinstagram.com` — whose OpenGraph tags carry the real
video, so Discord renders a playable inline player. We borrow that mechanism
(see Fletcher messagefuncs.py `instagram.com` preview block + `instagram_caption`,
and swag.py `ytdlp_download_function`).

Fletcher applies the fix automatically to every Instagram link and runs an
embed-probe dance to decide whether reposting adds value. Here the trigger is
explicit instead: Alex (or anyone) replies to a message containing an Instagram
link and @mentions MIST. No probing needed — he asked, so we post.

Two delivery paths, best first:
  1. If yt-dlp is installed and the reel fits the channel's upload limit, we
     download it and re-upload the mp4 as a real Discord attachment — plays
     inline, never depends on a third-party service staying up.
  2. Otherwise we post the kkinstagram link and let Discord unfurl it. We ride
     the post's caption along as message text (the bot embed carries none).

This handler is inserted at the FRONT of the message-handler chain so it claims
the Instagram-reply-mention before chatter (which would otherwise treat the
@mention as conversation). Anything that isn't an Instagram-reply-mention is
passed straight through (returns False) so chatter still works normally.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re

import discord

from handler import Context

log = logging.getLogger("fletcher")

# Instagram permalink shapes that carry media: /reel/, /p/ (posts, incl. image
# carousels and video), /tv/ (IGTV). reels.../share links normalize to these.
_INSTA_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)

# Caption gets trimmed before it rides along above the embed.
_CAPTION_MAX = 600
# Fallback upload ceiling when there's no guild (DMs): Discord's base limit.
_DEFAULT_UPLOAD_LIMIT = 25 * 1024 * 1024


def _find_instagram_url(message: discord.Message | None) -> str | None:
    """First Instagram permalink in a message's text or its existing embeds."""
    if message is None:
        return None
    # Forwarded messages keep the visible body in a snapshot, not .content.
    text = message.content or ""
    snaps = getattr(message, "message_snapshots", None)
    if snaps:
        text = " ".join([text] + [getattr(s, "content", "") or "" for s in snaps])
    m = _INSTA_RE.search(text)
    if m:
        return m.group(0)
    for embed in message.embeds:
        for candidate in (embed.url, getattr(embed, "title", None), getattr(embed, "description", None)):
            if candidate:
                m = _INSTA_RE.search(candidate)
                if m:
                    return m.group(0)
    return None


def _to_proxy(url: str, proxy_domain: str) -> str:
    """Rewrite instagram.com -> the embed-fixer host (default kkinstagram.com)."""
    return url.replace("www.", "").replace("instagram.com", proxy_domain)


async def _fetch_caption(url: str) -> str | None:
    """The post's caption via yt-dlp metadata (no media download). Optional —
    returns None if yt-dlp isn't installed or extraction fails. Mirrors
    Fletcher's instagram_caption: kkinstagram's bot embed has no description, so
    we surface the caption as message text above it."""
    try:
        import yt_dlp  # optional dependency
    except ImportError:
        return None
    try:
        opts = {"socket_timeout": 5, "quiet": True, "no_warnings": True}
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(params=opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await asyncio.wait_for(loop.run_in_executor(None, _extract), timeout=15.0)
        if isinstance(info, dict):
            return info.get("description") or None
    except Exception as e:  # noqa: BLE001 — best-effort, never block the embed
        log.debug("instagram caption fetch failed: %s", e)
    return None


async def _download_reel(url: str, size_limit: int) -> discord.File | None:
    """Download the reel with yt-dlp and return it as a discord.File, or None
    if yt-dlp is absent / the download fails / it exceeds size_limit. Adapted
    from Fletcher's ytdlp_download_function (swag.py)."""
    try:
        import yt_dlp  # optional dependency
    except ImportError:
        return None
    try:
        opts = {
            "socket_timeout": 5,
            "quiet": True,
            "no_warnings": True,
            "format": (
                f"best[ext=mp4][filesize<{size_limit}]/best[ext=mp4]/best[ext=webm]/best"
            ),
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(params=opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await asyncio.wait_for(loop.run_in_executor(None, _extract), timeout=20.0)
        if not isinstance(info, dict):
            return None
        # extract_info collapses the chosen format onto the top dict for a single
        # video; fall back to requested_downloads or the best listed format.
        fmt = info
        if not fmt.get("url"):
            if info.get("requested_downloads"):
                fmt = info["requested_downloads"][0]
            elif info.get("formats"):
                fmt = info["formats"][-1]
        media_url = fmt.get("url")
        if not media_url:
            return None
        headers = fmt.get("http_headers") or {"User-Agent": "Mozilla/5.0"}

        # aiohttp ships with discord.py; reuse it for the media fetch.
        import aiohttp

        async with aiohttp.ClientSession() as sess, sess.get(media_url, headers=headers) as resp:
            if resp.status != 200:
                return None
            blob = io.BytesIO(await resp.read())
        n = blob.getbuffer().nbytes
        if n == 0 or n > size_limit:
            return None
        ext = fmt.get("ext", "mp4")
        return discord.File(blob, f'{info.get("id", "reel")}.{ext}')
    except Exception as e:  # noqa: BLE001
        log.debug("instagram reel download failed: %s", e)
        return None


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("instagram")
    if not cfg.get("enabled", True):
        log.info("instagram module disabled in config")
        return
    proxy_domain = cfg.get("proxy_domain", "kkinstagram.com")
    # Off by default: the kkinstagram embed is reliable and cheap; a real
    # mp4 reupload needs yt-dlp + cookies and Instagram often blocks it.
    try_download = bool(cfg.get("reupload_video", False))

    ctx.quips.add("instagram.embed", [
        "There's your reel 🫡", "Now it actually plays 👀",
        "Discord's embed was being shy ✨", "Fixed it for you ^_^",
    ])

    async def embed_reel(message: discord.Message, ctx: Context) -> bool:
        me = ctx.client.user
        if me is None:
            return False
        # Must be a reply that @mentions MIST.
        if message.reference is None or me not in message.mentions:
            return False
        # Stay inside the servers we serve (DMs are fine too).
        if message.guild is not None and message.guild.id not in ctx.config.guild_ids:
            return False

        # Resolve the replied-to message and pull an Instagram link from it.
        ref = message.reference
        replied = ref.resolved if isinstance(ref.resolved, discord.Message) else ref.cached_message
        if replied is None and ref.message_id is not None:
            try:
                replied = await message.channel.fetch_message(ref.message_id)
            except discord.HTTPException:
                replied = None
        insta_url = _find_instagram_url(replied)
        if insta_url is None:
            return False  # not an Instagram-reply: let chatter have it

        log.info("instagram: embedding %s for %s", insta_url, message.author)
        try:
            async with message.channel.typing():
                size_limit = getattr(
                    getattr(message, "guild", None), "filesize_limit", _DEFAULT_UPLOAD_LIMIT
                )
                video = await _download_reel(insta_url, size_limit) if try_download else None
                if video is not None:
                    await message.reply(
                        ctx.quips.tag("", "instagram.embed").lstrip("\n"),
                        file=video, mention_author=False,
                    )
                    return True

                # Embed-fixer path: post the rewritten link with the caption.
                proxy_url = _to_proxy(insta_url, proxy_domain)
                caption = await _fetch_caption(insta_url)
                if caption:
                    caption = caption.strip()
                    if len(caption) > _CAPTION_MAX:
                        caption = caption[:_CAPTION_MAX].rstrip() + "…"
                    body = f"{proxy_url}\n{caption}"
                else:
                    body = proxy_url
                await message.reply(
                    ctx.quips.tag(body, "instagram.embed"), mention_author=False
                )
        except Exception:
            log.exception("instagram embed failed")
            try:
                await message.add_reaction("🚫")
            except discord.HTTPException:
                pass
        return True

    # Front of the chain: claim the reply-mention before chatter treats the
    # @mention as conversation. Modules load alphabetically (chatter < instagram),
    # so a plain append would land us after it.
    ctx.handler.message_handlers.insert(0, embed_reel)
    log.info("instagram reel embedder ready — proxy=%s, reupload=%s", proxy_domain, try_download)
