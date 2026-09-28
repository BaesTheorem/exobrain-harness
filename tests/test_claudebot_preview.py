"""claude-bot link previews: which links qualify, the host rewrites onto the
embed-fixer frontends, the repost decisions, and the dedup window."""

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/previewlinks.py"), reason="claude-bot not present"
)


def _pl():
    return load_script("claude-bot/previewlinks.py")


def test_previewable_links_dedup_order_and_angle_brackets():
    pl = _pl()
    text = (
        "look https://x.com/nasa/status/123 and again https://x.com/nasa/status/123 "
        "then <https://www.reddit.com/r/aww/s/abc> and https://www.tiktok.com/t/ZT8XT4HQM/."
    )
    assert pl.previewable_links(text) == [
        "https://x.com/nasa/status/123",
        "https://www.tiktok.com/t/ZT8XT4HQM/",
    ]


def test_kind_of_covers_each_host():
    pl = _pl()
    cases = {
        "https://twitter.com/a/status/1": "tweet",
        "https://mobile.x.com/a/status/1": "tweet",
        "https://xcancel.com/a/status/1": "tweet_mirror",
        "https://nitter.net/a/status/1": "tweet_mirror",
        "https://www.tiktok.com/@nasa/video/7689547576265149710": "tiktok",
        "https://vm.tiktok.com/ZMabc/": "tiktok",
        "https://www.instagram.com/reels/DZnugEeidkt": "instagram",
        "https://old.reddit.com/r/x/comments/1abc/title/": "reddit",
        "https://pidgie-core.tumblr.com/post/657448904898609152/moss-rug": "tumblr",
        "https://www.tumblr.com/pidgie-core/657448904898609152": "tumblr",
        "https://t.me/durov/123": "telegram",
        "https://fb.watch/abc123/": "facebook",
        "https://www.facebook.com/watch?v=1": "facebook",
        "https://b23.tv/AbC": "bilibili",
        "https://vkvideo.ru/video-1_2": "vk",
        "https://www.loom.com/share/abc123": "loom",
        "https://discord.com/channels/1/2/3": "discord",
    }
    for url, kind in cases.items():
        assert pl.kind_of(url) == kind, url
    assert pl.kind_of("https://example.com/") is None
    for kind in ("facebook", "bilibili", "vk", "loom", "snapchat"):
        assert kind in pl.YTDLP_KINDS


def test_skip_commands_and_opt_out():
    pl = _pl()
    assert pl.should_skip_message("!roll https://x.com/a/status/1")
    assert not pl.should_skip_message("!preview https://x.com/a/status/1")
    assert not pl.should_skip_message("! not a command")
    assert pl.should_skip_message("https://x.com/a/status/1 #NoFx")
    assert not pl.should_skip_message("https://x.com/a/status/1")


def test_spoiler_detection():
    pl = _pl()
    assert pl.is_link_spoilered("look || https://x.com/a/status/1 ||", "https://x.com/a/status/1")
    assert not pl.is_link_spoilered("||hidden|| https://x.com/a/status/1", "https://x.com/a/status/1")


def test_host_rewrites():
    pl = _pl()
    assert pl.tweet_fixup_url("https://mobile.twitter.com/NASA/status/99?s=20") == (
        "https://fixupx.com/NASA/status/99"
    )
    assert pl.tweet_fixup_url("https://xcancel.com/NASA/status/99") == "https://fixupx.com/NASA/status/99"
    assert pl.tweet_fixup_url("https://example.com/") is None
    assert pl.instagram_mirror_url("https://www.instagram.com/reels/DZnugEeidkt/?igsh=x") == (
        "https://kkinstagram.com/reel/DZnugEeidkt/"
    )
    assert pl.instagram_mirror_url("https://m.instagram.com/p/AbC_1-2") == "https://kkinstagram.com/p/AbC_1-2/"
    assert pl.reddit_mirror_url("https://old.reddit.com/r/x/comments/1/t/") == (
        "https://vxreddit.com/r/x/comments/1/t/"
    )
    assert pl.tumblr_mirror_url("https://www.tumblr.com/pidgie-core/657/slug") == "https://tpmblr.com/pidgie-core/657"
    assert pl.tumblr_mirror_url("https://pidgie-core.tumblr.com/post/657/slug") == "https://tpmblr.com/pidgie-core/657"
    assert pl.tumblr_post_info("https://www.tumblr.com/blog/view/pidgie-core/657") == ("pidgie-core", "657")
    assert pl.tiktok_mirror_url("https://www.tiktok.com/@nasa/video/1") == "https://tiktokez.com/@nasa/video/1"
    assert pl.tiktok_mirror_url("https://www.tiktok.com/t/ZT8XT4HQM/") is None
    assert pl.telegram_info("https://t.me/durov/123") == ("durov", "123")
    assert pl.discord_link_ids("https://ptb.discord.com/channels/1/2/3") == (1, 2, 3)


def test_parse_og_both_attribute_orders_and_probe():
    pl = _pl()
    body = (
        '<meta property="og:title" content="A &amp; B">'
        '<meta content="https://v/x.mp4" property="og:video:url">'
        '<meta name="twitter:card" content="player">'
    )
    og = pl.parse_og(body)
    assert og["og:title"] == "A & B"
    assert og["og:video:url"] == "https://v/x.mp4"
    assert pl.probe_from_response(200, "text/html", body).video
    assert pl.probe_from_response(200, "video/mp4", "").video  # kkinstagram redirect to the file
    assert pl.probe_from_response(404, "text/html", body).empty
    img = pl.probe_from_response(200, "text/html", '<meta property="og:image" content="i.jpg">')
    assert img.image == "i.jpg" and not img.video and not img.empty


def test_tweet_facts_and_decisions():
    pl = _pl()
    video = pl.tweet_facts({"tweet": {"text": "hi", "media": {"videos": [{}]}}})
    assert pl.tweet_decision(video, None) == (True, "tweet has video")
    quoted = pl.tweet_facts({"tweet": {"text": "hi", "quote": {"media": {"videos": [{}]}}}})
    assert quoted.videos == 1
    photos = pl.tweet_facts({"tweet": {"text": "hi", "media": {"photos": [{"url": "a"}, {"url": "b"}]}}})
    assert photos.photos == 2 and photos.photo_url == "a"
    assert pl.tweet_decision(photos, None)[0]
    text = pl.tweet_facts({"tweet": {"text": "x" * 300}})
    assert pl.tweet_needs_native_check(text)
    assert pl.tweet_decision(text, pl.NativeEmbed())[1] == "no usable native embed"
    placeholder = pl.NativeEmbed(found=True, description="Post",
                                 image_url="https://abs.twimg.com/rweb/ssr/default/x.png")
    assert pl.tweet_decision(text, placeholder)[1] == "no usable native embed"
    cut = pl.NativeEmbed(found=True, description="x" * 100)
    assert pl.tweet_decision(text, cut)[0]
    full = pl.NativeEmbed(found=True, description="x" * 300)
    assert pl.tweet_decision(text, full) == (False, "text fully shown, no media")
    one_photo = pl.tweet_facts({"tweet": {"text": "hi", "media": {"photos": [{"url": "a"}]}}})
    assert pl.tweet_decision(one_photo, pl.NativeEmbed(found=True, description="hi"))[0]
    assert not pl.tweet_decision(one_photo, pl.NativeEmbed(found=True, description="hi", image_url="a"))[0]
    assert pl.tweet_decision(pl.tweet_facts({}), None) == (False, "no tweet data")


def test_tumblr_verdict():
    pl = _pl()
    assert pl.tumblr_verdict(None) == "absent"
    assert pl.tumblr_verdict(pl.NativeEmbed(found=True, title="Tumblr")) == "bad"
    assert pl.tumblr_verdict(pl.NativeEmbed(found=True, title="Post by @x")) == "good"


def test_repost_text_and_footer():
    pl = _pl()
    line = pl.repost_line("https://fixupx.com/a/status/1", "https://discord.com/channels/1/2/3", spoilered=True)
    assert line.startswith("-# || [link](https://fixupx.com/a/status/1) ||")
    assert pl.FOOTER_SENTINEL in line and "(<https://discord.com/channels/1/2/3>)" in line
    bare = pl.repost_line("u", "j", unfurl=False)
    assert "(<u>)" in bare
    assert pl.with_footer(line, "j") == line  # never doubled
    extra = pl.with_footer("body", "j")
    assert extra.startswith("-# ") and extra.endswith("\nbody")


def test_instagram_caption_handling():
    pl = _pl()
    og = {"og:title": 'NASA on Instagram: "Launch day\n.\n.\n.\n#space"'}
    assert pl.instagram_og_caption(og) == "Launch day\n.\n.\n.\n#space"
    assert pl.trim_caption(pl.instagram_og_caption(og)) == "Launch day\n\n#space"
    assert pl.trim_caption("x" * 700).endswith("…")
    assert pl.trim_caption("hi", spoilered=True) == "||hi||"
    assert pl.trim_caption(" . \n . ") is None


def test_unroll_header_shapes():
    pl = _pl()
    assert pl.unroll_header("a", False, True, True, 1, "c", "g", 5) == "@__a__ at <t:5:R>:"
    assert "<#1>" in pl.unroll_header("a", True, False, True, 1, "c", "g", 5)
    assert "**#c** (g)" in pl.unroll_header("a", False, False, False, 1, "c", "g", 5)


def test_dedup_windows():
    pl = _pl()
    d = pl.Dedup()
    assert not d.duplicate(1, 2, "u", now=0.0)
    assert d.duplicate(1, 2, "u", now=30.0)
    assert not d.duplicate(1, 2, "u", now=100.0)  # a minute later is a fresh paste
    assert not d.duplicate(1, 3, "u", now=100.0)  # another person, own preview
    assert not d.tweet_duplicate(1, "9", now=0.0)
    assert d.tweet_duplicate(1, "9", now=200.0)
    assert not d.tweet_duplicate(1, "9", now=600.0)
