"""Link previews -- Fletcher's preview_messagelink_function for this bot.

Every message in a served guild (or a DM) is scanned for links Discord
unfurls badly or not at all. For each one MIST works out whether she can do
better and, only if so, replies with a preview:

  X / Twitter (+ nitter mirrors)   fxtwitter API says what the post carries;
                                   video and multi-photo posts always get the
                                   fixupx link, text posts only when Discord's
                                   own card is missing, a placeholder, or cut off
  TikTok                           short links are expanded; if Discord's unfurl
                                   has no player, the tiktokez link is probed and
                                   posted, else the video is re-uploaded by yt-dlp
  Instagram                        kkinstagram probed as Discord's crawler; a
                                   reel reposts with the caption above it, a
                                   dead post falls back to the cover still
  Reddit                           vxreddit, only when it adds a video
  Tumblr                           tpmblr, only when Discord rendered nothing
                                   or its generic "Tumblr" card
  Telegram                         a card built from the post's OpenGraph tags
  Facebook, Bilibili, VK, ok.ru,   no fixer exists: yt-dlp downloads the media
  Rutube, Newgrounds, Loom,        and it is re-uploaded as an attachment
  Snapchat                         (Facebook posts with no video get an OG card)
  discord.com/channels/... links   the linked message is quoted ("unrolled")

Every preview is a silent reply to the post it belongs to, carries a small
footer pointing reactions at the original and naming the dismiss button, and
(where the bot may) suppresses the original's own embed so the media isn't
doubled. React with the x on a preview to drop it (the poster, an admin or
the owner); deleting the original deletes its previews; editing a link into
a fresh post previews it. Wrap a link in <angle brackets> or put #nofx in the
message to opt out. `!preview` (or a telescope reaction, or replying to a
post with a bare @mention of MIST) asks for a preview on purpose.

The pure rules live in previewlinks.py so the tests can load them without
discord. This file is the gateway glue: fetching, waiting on Discord's
unfurl, posting, and the reaction/edit/delete plumbing.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from datetime import timezone
from typing import Any, cast

import aiohttp
import discord

import previewlinks as pl
from config import load_owner_username
from handler import Context

log = logging.getLogger("fletcher")

CRAWLER_UA = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)
# Facebook and VK only serve OpenGraph tags to unfurlers they recognise.
OG_CRAWLER_UA = "MIST/0.1 facebookexternalhit/1.1"

# How long to give Discord's crawler before judging its unfurl absent. Its
# MESSAGE_UPDATE usually lands well inside a second; a link it never unfurls
# costs the whole ceiling.
NATIVE_WAIT_SEC = 4.0
TWEET_WAIT_SEC = 6.0
PROBE_TIMEOUT_SEC = 20
PROBE_MAX_BYTES = 512 * 1024
YTDLP_TIMEOUT_SEC = 45
DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024
# Edits older than this never trigger a preview (Fletcher: 5 minutes).
EDIT_WINDOW_SEC = 300
TELESCOPE = "\U0001f52d"

_tasks: set[asyncio.Task] = set()


def _keep(task: asyncio.Task, what: str) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    def _done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            log.error("%s failed", what, exc_info=t.exception())

    task.add_done_callback(_done)


def effective_content(message: discord.Message) -> str:
    """For a Discord forward the visible body lives in the snapshot."""
    snaps = getattr(message, "message_snapshots", None)
    if snaps and len(snaps) == 1 and not message.content:
        return getattr(snaps[0], "content", "") or ""
    return message.content or ""


def effective_embeds(message: discord.Message) -> list[discord.Embed]:
    snaps = getattr(message, "message_snapshots", None)
    if snaps and len(snaps) == 1 and not message.embeds:
        return list(getattr(snaps[0], "embeds", []) or [])
    return list(message.embeds)


def native_embed(message: discord.Message, providers: tuple[str, ...] = (),
                 url_markers: tuple[str, ...] = ()) -> pl.NativeEmbed:
    """Discord's own unfurl of the link, reduced to what a decision needs."""
    embeds = effective_embeds(message)
    chosen = None
    for e in embeds:
        pname = (e.provider.name if e.provider else "") or ""
        if (providers and pname in providers) or (
            url_markers and e.url and any(m in e.url for m in url_markers)
        ):
            chosen = e
            break
    if chosen is None and embeds and not (providers or url_markers):
        chosen = embeds[0]
    if chosen is None:
        return pl.NativeEmbed()
    image = None
    if chosen.image and chosen.image.url:
        image = chosen.image.url
    elif chosen.thumbnail and chosen.thumbnail.url:
        image = chosen.thumbnail.url
    return pl.NativeEmbed(
        found=True,
        video=bool(chosen.video and chosen.video.url),
        image_url=image,
        description=chosen.description or "",
        title=chosen.title or "",
    )


class Previewer:
    def __init__(self, ctx: Context, cfg: dict):
        self.ctx = ctx
        self.client = ctx.client
        self.db = ctx.db
        self.cfg = cfg
        self.limit = max(1, min(int(cfg.get("max_per_message", 3)), pl.PREVIEW_LIMIT_CEILING))
        self.suppress_original = bool(cfg.get("suppress_original", True))
        self.reupload = bool(cfg.get("reupload", True))
        self.unroll = bool(cfg.get("unroll", True))
        self.hosts = {
            "tweet": cfg.get("tweet_host", "fixupx.com"),
            "tiktok": cfg.get("tiktok_host", "tiktokez.com"),
            "instagram": cfg.get("instagram_host", "kkinstagram.com"),
            "reddit": cfg.get("reddit_host", "vxreddit.com"),
            "tumblr": cfg.get("tumblr_host", "tpmblr.com"),
        }
        self.dedup = pl.Dedup()
        # message id -> (links already judged, when); feeds the edit path so
        # only a link that is new to the post gets previewed.
        self.judged: dict[int, tuple[set[str], float]] = {}
        self.probe_slots = asyncio.Semaphore(4)
        self.ytdlp_lock = asyncio.Lock()  # one download at a time (8GB machine)
        self.owner = (cfg.get("owner_username") or load_owner_username() or "").lower()
        self.timeout = aiohttp.ClientTimeout(total=PROBE_TIMEOUT_SEC)

    # --- entry points ---------------------------------------------------------
    def in_scope(self, message: discord.Message) -> bool:
        if message.guild is not None and message.guild.id not in self.ctx.config.guild_ids:
            return False
        return True

    def remember_judged(self, message_id: int, links: list[str]) -> None:
        now = time.monotonic()
        for mid in [m for m, (_, t) in self.judged.items() if now - t > 2 * EDIT_WINDOW_SEC]:
            del self.judged[mid]
        seen, _ = self.judged.get(message_id, (set(), now))
        self.judged[message_id] = (seen | set(links), now)

    async def preview_message(self, message: discord.Message, links: list[str] | None = None,
                              forced: bool = False) -> list[discord.Message]:
        """Preview the links in `message` (all of them by default). `forced`
        is a person asking (command, telescope, bare @mention): no dedup, no
        opt-out, and the whole limit applies to what they asked for."""
        text = effective_content(message)
        if links is None:
            if not forced and pl.should_skip_message(text, self.ctx.config.prefix):
                return []
            links = pl.previewable_links(text)
        if not links:
            return []
        if not forced and message.flags.suppress_embeds:
            # The poster already said "no embeds" on this message.
            return []
        group = links[: self.limit]
        self.remember_judged(message.id, links)
        out: list[discord.Message] = []
        for url in group:
            if not forced and self.dedup.duplicate(
                message.channel.id, message.author.id, url
            ):
                log.debug("preview: %s was just previewed here, skipping", url)
                continue
            try:
                posted = await self.preview_link(message, url, forced=forced)
            except discord.NotFound:
                posted = None
            except Exception:
                log.exception("preview of %s failed", url)
                posted = None
            if posted is not None:
                out.append(posted)
        return out

    async def preview_link(self, message: discord.Message, url: str,
                           forced: bool = False) -> discord.Message | None:
        kind = pl.kind_of(url)
        if kind is None:
            return None
        spoilered = pl.is_link_spoilered(effective_content(message), url)
        handler = {
            "discord": self._discord_link,
            "tweet": self._tweet,
            "tweet_mirror": self._tweet,
            "tiktok": self._tiktok,
            "instagram": self._instagram,
            "reddit": self._reddit,
            "tumblr": self._tumblr,
            "telegram": self._telegram,
        }.get(kind, self._ytdlp if kind in pl.YTDLP_KINDS else None)
        if handler is None:
            return None
        result = await handler(message, url, spoilered, forced)
        if result is None:
            return None
        content, files, embed, suppress = result
        return await self._post(message, url, content, files, embed, suppress)

    # --- posting ----------------------------------------------------------------
    async def _post(self, message: discord.Message, url: str, content: str | None,
                    files: list[discord.File], embed: discord.Embed | None,
                    suppress: bool) -> discord.Message | None:
        content = pl.with_footer(content or "", message.jump_url)
        if len(content) > 2000:
            content = content[:1990].rstrip() + "…"
        kwargs: dict = {
            "allowed_mentions": discord.AllowedMentions.none(),
            "silent": True,
            "reference": message.to_reference(fail_if_not_exists=False),
            "mention_author": False,
        }
        if files:
            kwargs["files"] = files
        if embed is not None:
            kwargs["embed"] = embed
        try:
            out = await message.channel.send(content, **kwargs)
        except discord.HTTPException as e:
            log.warning("preview send failed for %s: %s", url, e)
            return None
        suppressed = False
        if suppress and self.suppress_original and message.guild is not None:
            # Needs Manage Messages on other people's posts; without it the
            # original's own card just stays alongside the preview.
            try:
                await message.edit(suppress=True)
                suppressed = True
            except discord.Forbidden:
                log.debug("preview: no Manage Messages in %s, original not suppressed",
                          message.channel)
            except discord.HTTPException:
                pass
        self.db.add_link_preview(
            message.channel.id, message.id, message.author.id,
            out.channel.id, out.id, url, suppressed,
        )
        log.info("preview: %s for %s -> %s", pl.kind_of(url), message.author, url)
        return out

    async def unsuppress(self, channel_id: int, message_id: int) -> None:
        chan = self.client.get_channel(channel_id)
        if chan is None:
            try:
                chan = await self.client.fetch_channel(channel_id)
            except discord.HTTPException:
                return
        try:
            msg = await chan.fetch_message(message_id)  # type: ignore[union-attr]
            await msg.edit(suppress=False)
        except discord.HTTPException:
            pass

    # --- helpers ------------------------------------------------------------------
    async def wait_for_native(self, message: discord.Message,
                              max_wait: float = NATIVE_WAIT_SEC) -> discord.Message:
        """Refetch the post as soon as Discord has attached an embed to it,
        or after `max_wait` if it never does. An embed that landed before we
        started watching never dispatches again, so read first, then wait."""
        try:
            fresh = await message.channel.fetch_message(message.id)
        except discord.HTTPException:
            return message
        if effective_embeds(fresh):
            return fresh

        def landed(payload: discord.RawMessageUpdateEvent) -> bool:
            return payload.message_id == message.id and bool(payload.data.get("embeds"))

        try:
            await self.client.wait_for("raw_message_edit", check=landed, timeout=max_wait)
        except asyncio.TimeoutError:
            return fresh
        try:
            return await message.channel.fetch_message(message.id)
        except discord.HTTPException:
            return fresh

    async def probe(self, url: str, ua: str = CRAWLER_UA) -> pl.Probe:
        """Ask a frontend what it would hand Discord's crawler."""
        async with self.probe_slots:
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as s, s.get(
                    url, headers={"User-Agent": ua}, allow_redirects=True
                ) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    body = ""
                    if not ctype.lower().startswith("video/"):
                        raw = await resp.content.read(PROBE_MAX_BYTES)
                        body = raw.decode("utf-8", "replace")
                    return pl.probe_from_response(resp.status, ctype, body)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.debug("probe failed for %s: %s", url, e)
                return pl.Probe(status=0)

    async def fetch_og(self, url: str, ua: str = BROWSER_UA,
                       max_bytes: int = 2 * 1024 * 1024) -> dict[str, str]:
        async with self.probe_slots:
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as s, s.get(
                    url, headers={"User-Agent": ua}, allow_redirects=True
                ) as resp:
                    if resp.status != 200:
                        return {}
                    raw = await resp.content.read(max_bytes)
                    return pl.parse_og(raw.decode("utf-8", "replace"))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.debug("og fetch failed for %s: %s", url, e)
                return {}

    async def fetch_file(self, url: str, name: str, limit: int,
                         headers: dict | None = None) -> discord.File | None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s, s.get(
                url, headers=headers or {"User-Agent": BROWSER_UA}
            ) as resp:
                if resp.status != 200:
                    return None
                blob = io.BytesIO()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    blob.write(chunk)
                    if blob.tell() > limit:
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        if blob.tell() == 0:
            return None
        blob.seek(0)
        return discord.File(blob, name)

    @staticmethod
    def upload_limit(message: discord.Message) -> int:
        guild = message.guild
        return (guild.filesize_limit if guild else DEFAULT_UPLOAD_LIMIT) - 1024

    async def ytdlp_file(self, url: str, limit: int) -> discord.File | None:
        """Download the media behind `url` with yt-dlp and return it as a
        Discord attachment, or None (not installed, failed, too big)."""
        try:
            import yt_dlp  # optional dependency
        except ImportError:
            log.debug("yt-dlp not installed; no re-upload for %s", url)
            return None
        opts: dict[str, Any] = {
            "socket_timeout": 5, "quiet": True, "no_warnings": True,
            "format": f"best[ext=mp4][filesize<{limit}]/best[ext=mp4]/best[ext=webm]/best",
            "http_headers": {"User-Agent": BROWSER_UA},
        }

        def _extract():
            # yt-dlp types params as a TypedDict it never fully declares.
            with yt_dlp.YoutubeDL(params=cast(Any, opts)) as ydl:
                return ydl.extract_info(url, download=False)

        async with self.ytdlp_lock:
            loop = asyncio.get_running_loop()
            try:
                info = await asyncio.wait_for(loop.run_in_executor(None, _extract), YTDLP_TIMEOUT_SEC)
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 -- yt-dlp raises its own zoo
                log.debug("yt-dlp extract failed for %s: %s", url, e)
                return None
            if not isinstance(info, dict):
                return None
            info = dict(info)
            # extract_info collapses the chosen format onto the top dict for a
            # single video; fall back to requested_downloads / the last format.
            fmt: dict[str, Any] = info
            if not fmt.get("url"):
                requested = cast(list[dict[str, Any]], info.get("requested_downloads") or [])
                formats = cast(list[dict[str, Any]], info.get("formats") or [])
                if requested:
                    fmt = requested[0]
                elif formats:
                    fmt = formats[-1]
            media_url = fmt.get("url")
            if not media_url:
                return None
            headers = fmt.get("http_headers") or {"User-Agent": BROWSER_UA}
            name = f"{info.get('id', 'video')}.{fmt.get('ext', 'mp4')}"
            return await self.fetch_file(media_url, name, limit, headers)

    # --- per-host branches -------------------------------------------------------
    async def _tweet(self, message, url, spoilered, forced):
        info = pl.tweet_info(url)
        if not info:
            return None
        username, status_id = info
        fixup = pl.tweet_fixup_url(url, self.hosts["tweet"]) or url
        is_mirror = pl.kind_of(url) == "tweet_mirror"
        # A mirror defers to an earlier address of the same tweet; X's own
        # domains keep deciding for themselves.
        if not forced and self.dedup.tweet_duplicate(message.channel.id, status_id) and is_mirror:
            return None
        seen_at = time.monotonic()
        api_url = f"https://api.fxtwitter.com/{username}/status/{status_id}"
        data = {}
        async with self.probe_slots:
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as s, s.get(api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                log.debug("fxtwitter api failed for %s: %s", url, e)
        facts = pl.tweet_facts(data)
        native = None
        if pl.tweet_needs_native_check(facts):
            remaining = max(0.0, TWEET_WAIT_SEC - (time.monotonic() - seen_at))
            fresh = await self.wait_for_native(message, remaining)
            markers = ("x.com/", "twitter.com/") + ((url.split("/")[2] + "/",) if is_mirror else ())
            native = native_embed(fresh, ("Twitter", "X"), markers)
        repost, reason = pl.tweet_decision(facts, native)
        log.debug("fixvx %s: %s", "reposting" if repost else "skipping", reason)
        if not repost:
            return None
        return pl.repost_line(fixup, message.jump_url, spoilered), [], None, True

    async def _resolve_tiktok(self, url: str) -> str | None:
        """Expand a TikTok short code by reading its redirect."""
        if pl.tiktok_mirror_url(url):
            return url
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as s, s.get(
                url, headers={"User-Agent": BROWSER_UA}, allow_redirects=False
            ) as resp:
                loc = resp.headers.get("Location", "")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        loc = loc.split("?")[0]
        return loc if pl.tiktok_mirror_url(loc) else None

    async def _tiktok(self, message, url, spoilered, forced):
        long_url = await self._resolve_tiktok(url)
        fresh = await self.wait_for_native(message)
        native = native_embed(fresh, ("TikTok",), ("tiktok.com/",))
        if native.video and not forced:
            log.debug("tiktok: native embed plays, skipping")
            return None
        if long_url:
            mirror = pl.tiktok_mirror_url(long_url, self.hosts["tiktok"])
            if mirror and (await self.probe(mirror)).video:
                return pl.repost_line(mirror, message.jump_url, spoilered), [], None, True
        if self.reupload and long_url:
            async with message.channel.typing():
                video = await self.ytdlp_file(long_url, self.upload_limit(message))
            if video is not None:
                return pl.repost_line(url, message.jump_url, spoilered, unfurl=False), [video], None, True
        return None

    async def _instagram(self, message, url, spoilered, forced):
        mirror = pl.instagram_mirror_url(url, self.hosts["instagram"])
        canonical = pl.instagram_mirror_url(url, "www.instagram.com")
        if not mirror or not canonical:
            return None
        probe, fresh = await asyncio.gather(self.probe(mirror), self.wait_for_native(message))
        native = native_embed(fresh, ("Instagram",), ("instagram.com/",))
        info = pl.instagram_info(url)
        is_reel = bool(info and info[0] == "reel")
        if probe.video or (probe.image and not native.image_url):
            og = await self.fetch_og(canonical)
            caption = pl.trim_caption(pl.instagram_og_caption(og), spoilered)
            line = pl.repost_line(mirror, message.jump_url, spoilered)
            return (f"{caption}\n{line}" if caption else line), [], None, True
        if probe.empty and not native.found:
            # Every mirror came back empty and Discord rendered nothing: the
            # link is sitting there bare. Instagram's own page still answers
            # with the cover still and the caption, so upload the still.
            og = await self.fetch_og(canonical)
            image = og.get("og:image")
            if not image:
                return None
            ext = re.search(r"\.(\w{1,5})(?:\?|$)", image)
            still = await self.fetch_file(image, f"instagram.{ext.group(1).lower() if ext else 'jpg'}",
                                          8 * 1024 * 1024)
            if still is None:
                return None
            line = pl.repost_line(url, message.jump_url, spoilered, unfurl=False)
            if is_reel or "/reel/" in (og.get("og:url") or ""):
                line = f"-# cover image, the reel plays on Instagram\n{line}"
            caption = pl.trim_caption(pl.instagram_og_caption(og), spoilered)
            return (f"{caption}\n{line}" if caption else line), [still], None, False
        log.debug("instagram: native embed sufficient for %s", url)
        return None

    async def _reddit(self, message, url, spoilered, forced):
        mirror = pl.reddit_mirror_url(url, self.hosts["reddit"])
        probe, fresh = await asyncio.gather(self.probe(mirror), self.wait_for_native(message))
        native = native_embed(fresh)
        if probe.video and not native.video:
            return pl.repost_line(mirror, message.jump_url, spoilered), [], None, True
        log.debug("vxreddit: %s", "no video to add" if not probe.video else "native already plays")
        return None

    async def _tumblr(self, message, url, spoilered, forced):
        fresh = await self.wait_for_native(message)
        verdict = pl.tumblr_verdict(native_embed(fresh))
        if verdict == "good" and not forced:
            return None
        mirror = pl.tumblr_mirror_url(url, self.hosts["tumblr"])
        return pl.repost_line(mirror, message.jump_url, spoilered, label="Tumblr post"), [], None, True

    async def _telegram(self, message, url, spoilered, forced):
        info = pl.telegram_info(url)
        if not info:
            return None
        channel, post_id = info
        og = await self.fetch_og(f"https://t.me/{channel}/{post_id}")
        title, desc, image = og.get("og:title"), og.get("og:description"), og.get("og:image")
        if not (title or desc):
            return None
        embed = discord.Embed(url=url, colour=discord.Colour.from_rgb(0x2A, 0xAB, 0xEE))
        if title:
            embed.title = title[:256]
        if desc:
            embed.description = (f"||{desc[:2040]}||" if spoilered else desc[:2048])
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text=f"{og.get('og:site_name', 'Telegram')} · @{channel}")
        return None, [], embed, False

    async def _ytdlp(self, message, url, spoilered, forced):
        if self.reupload:
            async with message.channel.typing():
                video = await self.ytdlp_file(url, self.upload_limit(message))
            if video is not None:
                if spoilered:
                    video.filename = f"SPOILER_{video.filename}"
                return pl.repost_line(url, message.jump_url, spoilered, unfurl=False), [video], None, True
        if pl.kind_of(url) == "facebook":
            # Nothing downloadable: a text or photo post, or a video only shown
            # to logged-in users. Discord's unfurl is the login wall, so build
            # a card from the OG tags rather than leave the link with nothing.
            og = await self.fetch_og(url, OG_CRAWLER_UA)
            title, desc, image = og.get("og:title"), og.get("og:description"), og.get("og:image")
            if not (title or desc) or (title or "").lower() in ("facebook", "log in or sign up to view"):
                return None
            embed = discord.Embed(url=url, colour=discord.Colour.from_rgb(0x18, 0x77, 0xF2))
            if title:
                embed.title = title[:256]
            if desc:
                embed.description = desc[:2048]
            if image:
                embed.set_image(url=image)
            embed.set_footer(text="Facebook")
            return None, [], embed, False
        return None

    async def _discord_link(self, message, url, spoilered, forced):
        if not self.unroll:
            return None
        ids = pl.discord_link_ids(url)
        if not ids:
            return None
        guild_id, channel_id, message_id = ids
        guild = self.client.get_guild(guild_id)
        if guild is None:
            return None
        channel = guild.get_channel_or_thread(channel_id)
        if channel is None:
            return None
        try:
            member = guild.get_member(message.author.id) or await guild.fetch_member(message.author.id)
        except discord.HTTPException:
            return None
        # Only quote what the poster could read themselves.
        if not channel.permissions_for(member).read_message_history:
            return None
        try:
            target = await channel.fetch_message(message_id)  # type: ignore[union-attr]
        except discord.HTTPException:
            return None
        forwarded = False
        snaps = getattr(target, "message_snapshots", None)
        body, embeds, attachments = target.content, list(target.embeds), list(target.attachments)
        if snaps and len(snaps) == 1:
            snap = snaps[0]
            body = getattr(snap, "content", "") or ""
            embeds = list(getattr(snap, "embeds", []) or [])
            attachments = list(getattr(snap, "attachments", []) or [])
            forwarded = True
        embed = None
        if target.author.bot and embeds:
            embed = embeds[0]
        elif forwarded:
            embed = next((e for e in embeds if e.type == "rich"), None)
        ts = int(target.created_at.replace(tzinfo=timezone.utc).timestamp())
        header = pl.unroll_header(
            target.author.name, forwarded,
            same_channel=message.channel.id == channel_id,
            same_guild=bool(message.guild and message.guild.id == guild_id),
            channel_id=channel_id, channel_name=getattr(channel, "name", "?"),
            guild_name=guild.name, ts=ts,
        )
        content = f"{header}\n>>> {body}" if body else header
        src_nsfw = bool(getattr(channel, "is_nsfw", lambda: False)())
        dest_nsfw = message.guild is None or bool(getattr(message.channel, "is_nsfw", lambda: False)())
        hide = src_nsfw and not dest_nsfw
        if hide:
            content = re.sub(r"https?://\S+", lambda m: f"<{m.group(0)}>", content)
        files: list[discord.File] = []
        limit = self.upload_limit(message)
        for att in attachments:
            if att.size > limit:
                content += f"\n• <{att.url}>"
                continue
            try:
                blob = io.BytesIO()
                await att.save(blob)
                blob.seek(0)
            except discord.HTTPException:
                content += f"\n• <{att.url}>"
                continue
            name = f"SPOILER_{att.filename}" if hide else att.filename
            files.append(discord.File(blob, name, description=att.description))
        if len(content) > 1900:
            content = content[:1880].rstrip() + f"…\n-# <{url}>"
        return content, files, embed, False


def setup(ctx: Context) -> None:
    cfg = ctx.config.section("preview")
    if not cfg.get("enabled", True):
        log.info("preview module disabled in config")
        return
    pv = Previewer(ctx, cfg)
    me_id = lambda: ctx.client.user.id if ctx.client.user else 0  # noqa: E731

    def _bare_mention(message: discord.Message) -> bool:
        """A reply whose whole text is an @mention of MIST: 'embed that'."""
        if message.reference is None or ctx.client.user is None:
            return False
        if ctx.client.user not in message.mentions:
            return False
        rest = re.sub(rf"<@!?{me_id()}>", "", message.content or "").strip()
        return rest == ""

    async def on_message(message: discord.Message, ctx: Context) -> bool:
        if not pv.in_scope(message):
            return False
        if _bare_mention(message):
            ref = message.reference
            replied = ref.resolved if isinstance(ref.resolved, discord.Message) else ref.cached_message
            if replied is None and ref.message_id is not None:
                try:
                    replied = await message.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    replied = None
            if replied is not None and pl.previewable_links(effective_content(replied)):
                _keep(asyncio.create_task(pv.preview_message(replied, forced=True)), "preview")
                return True  # claimed: chatter shouldn't answer a bare mention
            return False
        if pl.previewable_links(effective_content(message)):
            _keep(asyncio.create_task(pv.preview_message(message)), "preview")
        return False

    async def on_raw_edit(payload: discord.RawMessageUpdateEvent, ctx: Context) -> None:
        data = payload.data
        if "content" not in data or payload.guild_id not in ctx.config.guild_ids:
            return
        # Snowflake -> age; edits to old posts never trigger a preview.
        created = ((payload.message_id >> 22) + 1420070400000) / 1000
        if time.time() - created > EDIT_WINDOW_SEC:
            return
        links = pl.previewable_links(data.get("content") or "")
        seen = pv.judged.get(payload.message_id, (set(), 0.0))[0]
        new = [u for u in links if u not in seen]
        if not new or pl.should_skip_message(data.get("content") or "", ctx.config.prefix):
            return
        chan = ctx.client.get_channel(payload.channel_id)
        if chan is None:
            return
        try:
            message = await chan.fetch_message(payload.message_id)  # type: ignore[union-attr]
        except discord.HTTPException:
            return
        if message.author.bot:
            return
        _keep(asyncio.create_task(pv.preview_message(message, links=new)), "preview (edit)")

    async def on_raw_delete(payload: discord.RawMessageDeleteEvent, ctx: Context) -> None:
        # A deleted post takes its previews with it.
        for row in ctx.db.previews_for_source(payload.message_id):
            chan = ctx.client.get_channel(row["preview_channel"])
            if chan is not None:
                try:
                    await chan.get_partial_message(row["preview_message"]).delete()  # type: ignore[union-attr]
                except discord.HTTPException:
                    pass
        ctx.db.forget_previews_for_source(payload.message_id)
        # A deleted preview hands the poster their own embed back.
        row = ctx.db.preview_by_message(payload.message_id)
        if row is not None:
            if row["source_suppressed"]:
                await pv.unsuppress(row["source_channel"], row["source_message"])
            ctx.db.forget_preview(payload.message_id)

    async def _may_dismiss(payload: discord.RawReactionActionEvent, source_author: int) -> bool:
        if payload.user_id == source_author:
            return True
        member = payload.member
        if member is None:
            return False
        if member.name.lower() == pv.owner:
            return True
        return ctx.handler.is_admin(member) or member.guild_permissions.manage_messages

    async def on_reaction(payload: discord.RawReactionActionEvent, ctx: Context) -> None:
        name = (payload.emoji.name or "").replace("️", "")
        if name == pl.DISMISS_EMOJI.replace("️", ""):
            row = ctx.db.preview_by_message(payload.message_id)
            if row is None or not await _may_dismiss(payload, row["source_author"]):
                return
            chan = ctx.client.get_channel(payload.channel_id)
            if chan is not None:
                try:
                    await chan.get_partial_message(payload.message_id).delete()  # type: ignore[union-attr]
                except discord.HTTPException:
                    pass
            if row["source_suppressed"]:
                await pv.unsuppress(row["source_channel"], row["source_message"])
            ctx.db.forget_preview(payload.message_id)
        elif name == TELESCOPE:
            if payload.guild_id not in ctx.config.guild_ids:
                return
            chan = ctx.client.get_channel(payload.channel_id)
            if chan is None:
                return
            try:
                message = await chan.fetch_message(payload.message_id)  # type: ignore[union-attr]
            except discord.HTTPException:
                return
            if message.author.id != me_id():
                _keep(asyncio.create_task(pv.preview_message(message, forced=True)), "preview (telescope)")

    ctx.handler.message_handlers.insert(0, on_message)
    ctx.handler.raw_message_edit_handlers.append(on_raw_edit)
    ctx.handler.raw_message_delete_handlers.append(on_raw_delete)
    ctx.handler.reaction_add_handlers.append(on_reaction)

    @ctx.handler.command(
        "!preview", "!embed", "!fix",
        description="Preview the links in the message you replied to, a pasted URL, or a message id",
        dm=True,
    )
    async def preview_cmd(message: discord.Message, args: list[str], ctx: Context) -> None:
        target: discord.Message | None = None
        links: list[str] | None = None
        if message.reference is not None and message.reference.message_id:
            try:
                target = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                target = None
        elif args and args[0].isdigit():
            try:
                target = await message.channel.fetch_message(int(args[0]))
            except discord.HTTPException:
                target = None
        elif args:
            target = message
            links = pl.previewable_links(" ".join(args))
        if target is None:
            await message.reply(
                "Reply to a message with `!preview`, or give me a link or a message id.",
                mention_author=False,
            )
            return
        posted = await pv.preview_message(target, links=links, forced=True)
        if not posted:
            try:
                await message.add_reaction("\U0001f937")  # shrug: nothing better to offer
            except discord.HTTPException:
                pass

    log.info(
        "link previews ready -- limit=%d/message, reupload=%s, unroll=%s, hosts=%s",
        pv.limit, pv.reupload, pv.unroll, json.dumps(pv.hosts, separators=(",", ":")),
    )

