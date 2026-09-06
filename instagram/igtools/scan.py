"""Scan every configured account and write one snapshot for local-events.

Output: data/kc-events-scan.json, shaped like the reddit module's snapshot so
the skill can gate on `status` the same way:
  ok       every account fetched (or individually marked missing/private)
  partial  Instagram throttled us mid-run; whatever was fetched is kept
  blocked  nothing fetched (no cookies, cooldown, throttled on request 1)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config, fetch
from . import session as sess


def run(
    accounts: list[str],
    since_days: int = 14,
    media: bool = False,
    force: bool = False,
    quiet: bool = False,
    out: Path = config.SCAN_OUT,
    transport: str = "browser",
    headless: bool = True,
    merge: bool = False,
) -> dict:
    """`merge=True` (a `--only` run) replaces just the scanned accounts inside
    the existing snapshot instead of overwriting the whole file."""
    started = datetime.now(timezone.utc)
    snap: dict = {
        "generated_at": started.astimezone().isoformat(timespec="seconds"),
        "window_days": since_days,
        "transport": transport,
        "status": "blocked",
        "accounts": [],
        "posts_total": 0,
        "errors": [],
    }

    def say(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr, flush=True)

    try:
        if transport == "browser":
            from . import browser

            reader = browser.BrowserSession(headless=headless, force=force)
            reader.__enter__()
            fetch_posts = reader.posts
        else:
            reader = None
            s_http = sess.Session.open(force=force)
            fetch_posts = lambda handle, since_days: fetch.posts(s_http, handle, since_days=since_days)
    except (RuntimeError, sess.Throttled) as exc:
        snap["errors"].append(str(exc))
        _write(out, snap)
        return snap

    throttled = False
    for n, handle in enumerate(accounts, 1):
        say(f"[{n}/{len(accounts)}] @{handle}")
        entry: dict = {"username": handle, "status": "ok", "posts": []}
        try:
            summary, posts = fetch_posts(handle, since_days=since_days)
            entry.update(summary)
            entry["posts"] = posts
        except sess.NotFound:
            entry["status"] = "missing"
            snap["errors"].append(f"@{handle}: not found (typo, renamed, or private)")
        except sess.Throttled as exc:
            entry["status"] = "throttled"
            snap["errors"].append(f"@{handle}: {exc}")
            snap["accounts"].append(entry)
            throttled = True
            break
        except Exception as exc:  # noqa: BLE001 - one bad account must not kill the run
            entry["status"] = "error"
            snap["errors"].append(f"@{handle}: {exc}")
        snap["accounts"].append(entry)

    if reader is not None:
        reader.__exit__(None, None, None)
    fetched = [a for a in snap["accounts"] if a["status"] == "ok"]
    snap["posts_total"] = sum(len(a["posts"]) for a in fetched)
    if throttled:
        snap["status"] = "partial" if fetched else "blocked"
    else:
        snap["status"] = "ok"

    if media and fetched:
        # CDN images need no session; a bare paced client is enough.
        _download_media(sess.Session(cookies=config.load_cookies()), fetched, say)

    if merge and out.exists():
        snap = _merge(json.loads(out.read_text()), snap, configured=set(config.load_accounts()))
    _write(out, snap)
    return snap


def _merge(prior: dict, fresh: dict, configured: set[str]) -> dict:
    """Replace the freshly scanned accounts, keep the rest, and drop any prior
    account that is no longer in the configured list (a retired handle)."""
    scanned = {a["username"] for a in fresh["accounts"]}
    kept = [a for a in prior.get("accounts", []) if a["username"] not in scanned and a["username"] in configured]
    merged = dict(prior)
    merged["accounts"] = kept + fresh["accounts"]
    merged["posts_total"] = sum(len(a["posts"]) for a in merged["accounts"] if a["status"] == "ok")
    live = {a["username"] for a in merged["accounts"]}
    merged["errors"] = [e for e in prior.get("errors", []) if _error_account(e) in live - scanned] + fresh["errors"]
    merged["generated_at"] = fresh["generated_at"]
    merged["status"] = fresh["status"] if fresh["status"] != "ok" else prior.get("status", "ok")
    merged["merged_accounts"] = sorted(scanned)
    return merged


def _download_media(s: sess.Session, accounts: list[dict], say) -> None:
    """Save the first image of every post so a vision pass can read flyers.
    Skips files already on disk; CDN URLs expire, so this is the durable copy."""
    for a in accounts:
        folder = config.MEDIA / a["username"]
        for p in a["posts"]:
            if not p.get("images"):
                continue
            dest = folder / f"{p['code']}.jpg"
            p["local_media"] = str(dest)
            if dest.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(s.get_bytes(p["images"][0], referer=p["url"]))
                say(f"  saved {dest.relative_to(config.ROOT)}")
            except Exception as exc:  # noqa: BLE001 - a missing thumbnail is not fatal
                p["local_media"] = None
                say(f"  media failed for {p['code']}: {exc}")


def _write(out: Path, snap: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, ensure_ascii=False))


def _error_account(err: str) -> str | None:
    return err[1:].split(":", 1)[0] if err.startswith("@") and ":" in err else None
