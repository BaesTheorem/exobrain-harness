#!/usr/bin/env python3
"""Mirror becomingstronger.substack.com posts into the site's posts.json.

Runs locally rather than in GitHub Actions: Substack's edge returns 403 to
GitHub's datacenter IPs, so the Actions version of this never once succeeded.
A residential IP gets a clean 200, so the job lives here instead.

Writes posts.json in the site repo, commits, and pushes only when the content
actually changed. Silent on a no-op run.
"""

import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED = "https://becomingstronger.substack.com/feed"
SITE_REPO = Path(
    os.environ.get(
        "BECOMINGSTRONGER_REPO",
        Path.home() / "Documents" / "becomingstronger.github.io",
    )
)
POSTS_JSON = SITE_REPO / "posts.json"
MAX_POSTS = 12
LOG = Path(__file__).resolve().parent / "sync.log"
NOTIFY = (
    Path(__file__).resolve().parent.parent / "mist-voice" / "bin" / "mist-notify"
)
SITE_URL = "https://becomingstronger.org"
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def notify(msg, title="MIST", sound="Purr", link=SITE_URL):
    if not NOTIFY.exists():
        return
    subprocess.run([str(NOTIFY), msg, title, sound, link], check=False)


def fetch_feed():
    req = urllib.request.Request(
        FEED, headers={"User-Agent": "becomingstronger.github.io blog mirror"}
    )
    return urllib.request.urlopen(req, timeout=30).read()


def parse(xml_bytes):
    """Parse the RSS into the post records the Blog tab renders.

    Kept deliberately identical to the retired Actions workflow so switching
    runners produces no spurious diff in posts.json.
    """
    channel = ET.fromstring(xml_bytes).find("channel")
    posts = []
    for item in channel.findall("item")[:MAX_POSTS]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        body = item.findtext("content:encoded", namespaces=NS) or ""

        img = ""
        enc = item.find("enclosure")
        if enc is not None and (enc.get("type") or "").startswith("image"):
            img = enc.get("url") or ""
        if not img:
            m = re.search(r'<img[^>]+src="([^"]+)"', body or desc)
            if m:
                img = html.unescape(m.group(1))
        img = re.sub(r"w_\d+,c_limit", "w_800,c_limit", img)

        desc = html.unescape(re.sub(r"<[^>]+>", "", desc)).strip()
        if len(desc) > 180:
            desc = desc[:177].rsplit(" ", 1)[0] + "..."

        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "").strftime(
                "%Y-%m-%d"
            )
        except Exception:
            date = ""

        posts.append(
            {
                "title": title,
                "link": link,
                "date": date,
                "excerpt": desc,
                "image": img,
            }
        )
    return posts


def git(*args, check=True):
    return subprocess.run(
        ["git", "-C", str(SITE_REPO), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def publish(new_titles):
    git("add", "posts.json")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return False

    git("-c", "user.name=substack-sync", "-c",
        "user.email=actions@users.noreply.github.com",
        "commit", "-m", "Sync Substack posts")

    if git("push", check=False).returncode != 0:
        # Local clone was behind. Rebase onto the remote and retry once.
        log("push rejected, rebasing onto origin/main")
        git("pull", "--rebase")
        git("push")
    log(f"pushed: {', '.join(new_titles) if new_titles else 'metadata only'}")
    return True


def main():
    if not POSTS_JSON.parent.is_dir():
        log(f"FAIL site repo missing at {SITE_REPO}")
        return 1

    try:
        posts = parse(fetch_feed())
    except urllib.error.HTTPError as exc:
        log(f"FAIL feed returned HTTP {exc.code}")
        return 1
    except Exception as exc:
        log(f"FAIL {type(exc).__name__}: {exc}")
        return 1

    if not posts:
        log("FAIL feed parsed to zero posts, refusing to overwrite posts.json")
        return 1

    old = []
    if POSTS_JSON.exists():
        try:
            old = json.loads(POSTS_JSON.read_text())
        except Exception:
            pass

    if old == posts:
        log(f"no change ({len(posts)} posts)")
        return 0

    old_links = {p.get("link") for p in old}
    new_titles = [p["title"] for p in posts if p["link"] not in old_links]

    with POSTS_JSON.open("w") as fh:
        json.dump(posts, fh, indent=1)

    if publish(new_titles):
        if new_titles:
            headline = new_titles[0]
            extra = f" (+{len(new_titles) - 1} more)" if len(new_titles) > 1 else ""
            notify(f"New Substack post synced to the site: {headline}{extra}")
        log(f"synced {len(posts)} posts, {len(new_titles)} new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
