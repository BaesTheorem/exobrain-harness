"""Link-preview logic for the Discord bot, with no Discord dependency so the
tests can load it on its own. modules/preview.py is the gateway glue.

This is the pure half of Fletcher's preview_messagelink_function: which links
qualify, how each host is rewritten onto its embed-fixer frontend, and the
rules that decide whether a repost adds anything over Discord's own unfurl.
The rules are Fletcher's (messagefuncs.py), trimmed to the sites a friend
group actually pastes.

The mechanism everywhere is the same. Discord unfurls some hosts badly (X
without the video, Instagram as a login wall, Reddit video as a still) or
not at all (Tumblr, TikTok). A community-run frontend for each host serves
the same post with OpenGraph tags Discord can render, so reposting the
link with the host swapped gets an inline player. Where no frontend exists
(Facebook, Bilibili, VK, ...) yt-dlp downloads the media and the bot
re-uploads it as an attachment instead.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field

# --- what counts as a previewable link -------------------------------------
# Each pattern refuses a link wrapped in <angle brackets> (the lookbehind), which
# is Discord's own "don't unfurl this" spelling and ours too.
PATTERNS: dict[str, re.Pattern[str]] = {
    "discord": re.compile(
        r"(?<!<)(https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/\d+/\d+/\d+)",
        re.IGNORECASE,
    ),
    "tweet": re.compile(
        r"(?<!<)(https?://(?:m\.|www\.|mobile\.)?(?:twitter\.com|x\.com)/[^/\s]+/status/\d+)",
        re.IGNORECASE,
    ),
    # Nitter mirrors: same author/status path, no unfurl anywhere.
    "tweet_mirror": re.compile(
        r"(?<!<)(https?://(?:www\.)?(?:xcancel\.com|nitter\.[a-z0-9-]+(?:\.[a-z0-9-]+)*)/[^/\s]+/status/\d+)",
        re.IGNORECASE,
    ),
    "tiktok": re.compile(
        r"(?<!<)(https?://(?:www\.|m\.)?tiktok\.com/(?:@[^\s/]+/(?:video|photo)/\d+|t/[A-Za-z0-9]+)/?"
        r"|https?://v[mt]\.tiktok\.com/[A-Za-z0-9]+/?)",
        re.IGNORECASE,
    ),
    # Shortcode with and without the trailing slash, from www./m./bare host,
    # /reel/ or /reels/; stops before ?igsh= share tracking.
    "instagram": re.compile(
        r"(?<!<)(https?://(?:www\.|m\.)?instagram\.com/(?:reels?|p|tv)/[A-Za-z0-9_-]+/?)",
        re.IGNORECASE,
    ),
    # ")" excluded from the tail so a masked [text](url) link doesn't hand the
    # closing paren to the frontend.
    "reddit": re.compile(
        r"(?<!<)(https?://(?:www\.|old\.|new\.)?reddit\.com/r/[^/\s]+/(?:comments|s)/[^\s<)]+)",
        re.IGNORECASE,
    ),
    "tumblr": re.compile(
        r"(?<!<)(https?://(?:www\.)?tumblr\.com/(?:blog/view/)?[^/\s]+/\d+[^\s<)]*"
        r"|https?://[a-z0-9-]+\.tumblr\.com/(?:post|image)/\d+[^\s<)]*)",
        re.IGNORECASE,
    ),
    "telegram": re.compile(r"(?<!<)(https?://t\.me/[^/\s]+/\d+)", re.IGNORECASE),
    "facebook": re.compile(
        r"(?<!<)(https?://(?:www\.|m\.|web\.)?facebook\.com/(?:watch|reel|share|[^/\s]+/(?:videos|posts))[^\s<)]*"
        r"|https?://fb\.watch/[^\s<)]+)",
        re.IGNORECASE,
    ),
    "bilibili": re.compile(
        r"(?<!<)(https?://(?:www\.|m\.)?bilibili\.com/video/[A-Za-z0-9]+|https?://b23\.tv/[A-Za-z0-9]+)",
        re.IGNORECASE,
    ),
    "vk": re.compile(
        r"(?<!<)(https?://(?:www\.|m\.|new\.)?vk(?:(?:video)?\.ru|\.com)/(?:video|clip)-?\d+_\d+)",
        re.IGNORECASE,
    ),
    "okru": re.compile(r"(?<!<)(https?://(?:www\.|m\.)?ok\.ru/video/\d+)", re.IGNORECASE),
    "rutube": re.compile(
        r"(?<!<)(https?://rutube\.ru/(?:video|shorts|play/embed)/[a-z0-9]+/?)", re.IGNORECASE
    ),
    "newgrounds": re.compile(
        r"(?<!<)(https?://www\.newgrounds\.com/(?:portal/view|audio/listen)/\d+)", re.IGNORECASE
    ),
    "loom": re.compile(r"(?<!<)(https?://(?:www\.)?loom\.com/share/[a-z0-9]+)", re.IGNORECASE),
    "snapchat": re.compile(
        r"(?<!<)(https?://(?:www\.)?snapchat\.com/spotlight/[^\s<)]+|https?://t\.snapchat\.com/[^\s<)]+)",
        re.IGNORECASE,
    ),
}

# Hosts with no embed-fixer frontend: the media is downloaded and re-uploaded.
YTDLP_KINDS = frozenset(
    {"facebook", "bilibili", "vk", "okru", "rutube", "newgrounds", "loom", "snapchat"}
)

_ANY = re.compile("|".join(p.pattern for p in PATTERNS.values()), re.IGNORECASE)

# A post is previewed for at most this many links however high the config
# goes: each preview is its own message.
PREVIEW_LIMIT_CEILING = 5
# The opt-out tag: anywhere in the message means leave every link alone.
OPT_OUT_TAG = "#nofx"


def kind_of(url: str) -> str | None:
    for name, pat in PATTERNS.items():
        if pat.fullmatch(url):
            return name
    return None


def previewable_links(content: str) -> list[str]:
    """Every previewable link in a message, in the order written, repeats
    collapsed (pasting a link twice is one link to preview)."""
    links: list[str] = []
    for m in _ANY.finditer(content or ""):
        url = m.group(0).rstrip(".,;:!?'\"")
        if url not in links:
            links.append(url)
    return links


def should_skip_message(content: str, prefix: str = "!") -> bool:
    """Command messages (prefix + a letter) and #nofx posts get no preview.
    `!preview` itself is the exception, since it asks for one."""
    text = content or ""
    if OPT_OUT_TAG in text.lower():
        return True
    stripped = text.lstrip()
    if (
        len(stripped) > len(prefix)
        and stripped.startswith(prefix)
        and stripped[len(prefix)].isalpha()
        and not stripped.lower().startswith(f"{prefix}preview")
    ):
        return True
    return False


def is_link_spoilered(content: str, link: str) -> bool:
    """True when the link sits inside || spoiler bars ||."""
    parts = (content or "").split("||")
    idx = next((i for i, seg in enumerate(parts) if link in seg), 0)
    return idx % 2 == 1


# --- host rewrites ------------------------------------------------------------
_TWEET_INFO = re.compile(
    r"(?:twitter\.com|x\.com|xcancel\.com|nitter\.[a-z0-9.-]+)/([^/\s]+)/status/(\d+)",
    re.IGNORECASE,
)


def tweet_info(url: str) -> tuple[str, str] | None:
    """(username, status id) for any tweet address, or None."""
    m = _TWEET_INFO.search(url)
    return (m.group(1), m.group(2)) if m else None


def tweet_fixup_url(url: str, host: str = "fixupx.com") -> str | None:
    """The fxembed address for a tweet. Rebuilt from author + id so mirrors
    and mobile hosts all land on the same canonical form."""
    info = tweet_info(url)
    if not info:
        return None
    return f"https://{host}/{info[0]}/status/{info[1]}"


_INSTA_INFO = re.compile(
    r"instagram\.com/(reels?|p|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE
)


def instagram_info(url: str) -> tuple[str, str] | None:
    """(kind, shortcode) with /reels/ folded into /reel/."""
    m = _INSTA_INFO.search(url)
    if not m:
        return None
    kind = m.group(1).lower()
    return ("reel" if kind == "reels" else kind, m.group(2))


def instagram_mirror_url(url: str, host: str = "kkinstagram.com") -> str | None:
    """Canonical https://<host>/<kind>/<shortcode>/ for a post or reel."""
    info = instagram_info(url)
    return f"https://{host}/{info[0]}/{info[1]}/" if info else None


def reddit_mirror_url(url: str, host: str = "vxreddit.com") -> str:
    """Swap the host including the www/old/new subdomains, so old.reddit.com
    never becomes old.<host> (not a valid host)."""
    return re.sub(r"https?://(?:www\.|old\.|new\.)?reddit\.com", f"https://{host}", url, count=1)


_TUMBLR_INFO = re.compile(
    r"https?://(?:www\.)?tumblr\.com/(?:blog/view/)?([^/\s]+)/(\d+)"
    r"|https?://([a-z0-9-]+)\.tumblr\.com/(?:post|image)/(\d+)",
    re.IGNORECASE,
)


def tumblr_post_info(url: str) -> tuple[str, str] | None:
    """(blog, post id) for either Tumblr URL shape, or None."""
    m = _TUMBLR_INFO.search(url)
    if not m:
        return None
    return (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))


def tumblr_mirror_url(url: str, host: str = "tpmblr.com") -> str:
    """Canonical https://<host>/<blog>/<id>; the subdomain shape only gets
    there through a redirect, so rebuild rather than swap the host."""
    info = tumblr_post_info(url)
    if info:
        return f"https://{host}/{info[0]}/{info[1]}"
    return url.replace("tumblr.com", host, 1)


_TIKTOK_LONG = re.compile(r"tiktok\.com/@[^\s/]+/(?:video|photo)/\d+", re.IGNORECASE)


def tiktok_mirror_url(url: str, host: str = "tiktokez.com") -> str | None:
    """Only the long /@user/video/<id> shape: the frontends don't resolve
    TikTok's short codes, so those must be expanded first."""
    if not _TIKTOK_LONG.search(url):
        return None
    return re.sub(r"https?://(?:www\.|m\.)?tiktok\.com", f"https://{host}", url, count=1)


_TELEGRAM_INFO = re.compile(r"t\.me/([^/\s]+)/(\d+)", re.IGNORECASE)


def telegram_info(url: str) -> tuple[str, str] | None:
    m = _TELEGRAM_INFO.search(url)
    return (m.group(1), m.group(2)) if m else None


_DISCORD_LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", re.IGNORECASE)


def discord_link_ids(url: str) -> tuple[int, int, int] | None:
    m = _DISCORD_LINK.search(url)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# --- OpenGraph probing ------------------------------------------------------
_META_PV = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']((?:og|twitter):[a-z:_]+)[\"'][^>]*content=[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_META_VP = re.compile(
    r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']((?:og|twitter):[a-z:_]+)[\"']",
    re.IGNORECASE,
)


def parse_og(body: str) -> dict[str, str]:
    """og:* and twitter:* meta tags, first occurrence wins, keys lowercased
    without the prefix collapsed (so 'og:video' and 'twitter:player:stream'
    are distinct)."""
    tags: dict[str, str] = {}
    for key, value in _META_PV.findall(body or ""):
        tags.setdefault(key.lower(), html.unescape(value))
    for value, key in _META_VP.findall(body or ""):
        tags.setdefault(key.lower(), html.unescape(value))
    return tags


@dataclass
class Probe:
    """What a frontend offered Discord's crawler for a link."""

    status: int = 0
    video: bool = False
    image: str | None = None
    title: str | None = None
    description: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.video or self.image)


def probe_from_response(status: int, content_type: str | None, body: str) -> Probe:
    """Classify a crawler-UA fetch of a frontend link. A frontend that answers
    with the media file itself (kkinstagram 302s the crawler straight to the
    mp4) counts as video just like og:video tags do."""
    if status != 200:
        return Probe(status=status)
    if content_type and content_type.split(";")[0].strip().lower().startswith("video/"):
        return Probe(status=status, video=True)
    og = parse_og(body)
    video = any(
        og.get(k)
        for k in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream")
    ) or og.get("twitter:card", "").lower() == "player"
    return Probe(
        status=status,
        video=bool(video),
        image=og.get("og:image") or og.get("twitter:image"),
        title=og.get("og:title"),
        description=og.get("og:description"),
    )


# --- native-embed classification -------------------------------------------
@dataclass
class NativeEmbed:
    """The bits of Discord's own unfurl a decision needs."""

    found: bool = False
    video: bool = False
    image_url: str | None = None
    description: str = ""
    title: str = ""


# X answers a rate-limited crawler with a generic "Post" card: well-formed,
# so every "is the native embed good enough?" test says yes.
PLACEHOLDER_IMAGE_MARKERS = (
    "abs.twimg.com/rweb/ssr/default/",
    "abs.twimg.com/responsive-web/client-web/icon-default",
)
PLACEHOLDER_DESCRIPTIONS = frozenset({"post", "tweet", "x"})


def is_placeholder_unfurl(image_url: str | None, description: str | None) -> bool:
    if image_url and any(m in image_url for m in PLACEHOLDER_IMAGE_MARKERS):
        return True
    if not image_url:
        return (description or "").strip().lower() in PLACEHOLDER_DESCRIPTIONS
    return False


# A native description this much shorter than the API text counts as cut off;
# the slack absorbs Discord's markdown escaping.
TWEET_TEXT_CUTOFF_SLACK = 100


@dataclass
class TweetFacts:
    found: bool = False
    text: str = ""
    videos: int = 0
    photos: int = 0
    photo_url: str | None = None


def tweet_facts(api_json: dict) -> TweetFacts:
    """Read the fxtwitter API answer. A quote-tweet carries its media on the
    post it quotes, and no native X embed ever plays that, so count both."""
    tweet = (api_json or {}).get("tweet") or {}
    facts = TweetFacts(found=bool(tweet), text=tweet.get("text") or "")
    for post in (tweet, tweet.get("quote") or {}):
        media = post.get("media") or {}
        facts.videos += len(media.get("videos") or [])
        photos = media.get("photos") or []
        if photos and not facts.photos:
            facts.photos = len(photos)
            facts.photo_url = photos[0].get("url")
    return facts


def tweet_needs_native_check(facts: TweetFacts) -> bool:
    """Video and multi-photo tweets repost unconditionally; anything else is
    judged against what Discord rendered."""
    return facts.found and not (facts.videos or facts.photos > 1)


def tweet_decision(facts: TweetFacts, native: NativeEmbed | None) -> tuple[bool, str]:
    """(repost?, reason). `native` is None when no native check was run."""
    if not facts.found:
        return False, "no tweet data"
    if facts.videos:
        return True, "tweet has video"
    if facts.photos > 1:
        return True, f"tweet has {facts.photos} photos"
    n = native or NativeEmbed()
    if n.found and is_placeholder_unfurl(n.image_url, n.description):
        n = NativeEmbed()
    if not n.found:
        return True, "no usable native embed"
    if len(facts.text) > len(n.description) + TWEET_TEXT_CUTOFF_SLACK:
        return True, f"native embed cuts text at {len(n.description)}/{len(facts.text)}"
    if not facts.photos:
        return False, "text fully shown, no media"
    if not n.image_url:
        return True, "tweet has a photo the native embed lacks"
    return False, "native embed sufficient"


def tumblr_verdict(native: NativeEmbed | None) -> str:
    """'absent', 'bad' (Tumblr's generic card) or 'good'."""
    if native is None or not native.found:
        return "absent"
    if native.title == "Tumblr" or "Pure effervescent enrichment" in (native.description or ""):
        return "bad"
    return "good"


# --- repost text ------------------------------------------------------------
# Additive previews check for this before prepending the footer, so it has to
# stay a stable substring of what dismiss_hint() builds.
FOOTER_SENTINEL = "react to the [original post]"
DISMISS_EMOJI = "✖️"  # heavy multiplication x, the dismiss button


def dismiss_hint(jump_url: str) -> str:
    """Footer every preview carries: push reactions onto the poster's message,
    and say what the x on this one does (so it reads as a button on the
    preview, not a verdict on the link)."""
    return f"{FOOTER_SENTINEL}(<{jump_url}>) · {DISMISS_EMOJI} here drops this preview"


def repost_line(url: str, jump_url: str, spoilered: bool = False, label: str = "link",
                unfurl: bool = True) -> str:
    """Body for a repost whose only content is a link. Small text keeps the
    line unobtrusive so the embed dominates. Links still unfurl inside -#
    lines; a <>-wrapped one never does (unfurl=False when the message carries
    its own attachment and the link is attribution only)."""
    body = f"[{label}]({url if unfurl else f'<{url}>'})"
    if spoilered:
        body = f"|| {body} ||"
    return f"-# {body} · {dismiss_hint(jump_url)}"


def with_footer(content: str, jump_url: str) -> str:
    """Prepend the footer to an additive preview (unroll, Telegram card, a
    re-uploaded video) that doesn't already carry it."""
    if FOOTER_SENTINEL in (content or ""):
        return content
    hint = f"-# {dismiss_hint(jump_url)}"
    return f"{hint}\n{content}" if content else hint


CAPTION_MAX = 600
_SPACER_LINE = re.compile("^[\\s.·•‧∙・⠀​‌ㅤ﻿]*$")


def strip_caption_spacer_lines(caption: str | None) -> str:
    """Drop the fold-pushing spacer lines Instagram captions carry (a lone
    dot per line above the hashtags). Blank runs collapse to one."""
    kept = ["" if _SPACER_LINE.match(line) else line for line in (caption or "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


_OG_CAPTION = re.compile(r'"(.*)"', re.DOTALL)


def instagram_og_caption(og: dict[str, str]) -> str | None:
    """Instagram quotes the caption at the end of og:title ('<Name> on
    Instagram: "<caption>"') and og:description. Span the outermost pair."""
    for key in ("og:title", "og:description"):
        m = _OG_CAPTION.search(og.get(key) or "")
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def trim_caption(caption: str | None, spoilered: bool = False) -> str | None:
    text = strip_caption_spacer_lines(caption)
    if not text:
        return None
    if len(text) > CAPTION_MAX:
        text = text[:CAPTION_MAX].rstrip() + "…"
    return f"||{text}||" if spoilered else text


# --- unroll (Discord message links) ----------------------------------------
def unroll_header(author: str, forwarded: bool, same_channel: bool, same_guild: bool,
                  channel_id: int, channel_name: str, guild_name: str, ts: int) -> str:
    fwd = " forwarded" if forwarded else ""
    when = f"<t:{ts}:R>"
    if same_channel:
        return f"@__{author}__{fwd} at {when}:"
    if same_guild:
        return f"@__{author}__{fwd} in <#{channel_id}> at {when}:"
    return f"@__{author}__{fwd} in **#{channel_name}** ({guild_name}) at {when}:"


# --- dedup ------------------------------------------------------------------
PREVIEW_DEDUP_SEC = 60
TWEET_DEDUP_SEC = 300


@dataclass
class Dedup:
    """One preview per paste. A reel preview takes seconds to decide, and
    someone who thinks nothing is happening pastes the link again inside
    that window. Recorded before any awaiting so concurrent copies see each
    other. Tweets are also keyed by status id across every address (x.com
    and a nitter mirror of it are the same post)."""

    window: float = PREVIEW_DEDUP_SEC
    tweet_window: float = TWEET_DEDUP_SEC
    _seen: dict[tuple, float] = field(default_factory=dict)
    _tweets: dict[tuple, float] = field(default_factory=dict)

    def _sweep(self, store: dict, window: float, now: float) -> None:
        for key in [k for k, t in store.items() if now - t > window]:
            del store[key]

    def duplicate(self, channel_id: int | None, author_id: int | None, url: str,
                  now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._sweep(self._seen, self.window, now)
        key = (channel_id, author_id, url)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def tweet_duplicate(self, channel_id: int | None, status_id: str,
                        now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._sweep(self._tweets, self.tweet_window, now)
        key = (channel_id, status_id)
        seen = key in self._tweets
        self._tweets[key] = now
        return seen
