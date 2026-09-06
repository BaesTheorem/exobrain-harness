"""Read an account's profile and recent posts, normalized to one record shape.

Two endpoints, two payload shapes, one parser each:
- `web_profile_info` (GraphQL "node" shape): profile fields + the newest 12
  posts. One request, and the one that proves the session works.
- `feed/user/<pk>/` ("items" shape): paginated timeline via `max_id`, used
  only when the window needs more than the profile's 12.

Both carry `accessibility_caption`, Instagram's own alt-text generator, which
transcribes flyer text ("May be an image of text that says 'FRI SEPT 12 ...'").
That is free OCR and it is kept on every record.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import session as sess


def profile(s: sess.Session, username: str) -> dict:
    ref = f"{sess.BASE}/{username}/"
    data = s.get_json("/api/v1/users/web_profile_info/", {"username": username}, referer=ref)
    user = (data.get("data") or {}).get("user")
    if not user:
        raise sess.NotFound(username)
    return user


def posts(s: sess.Session, username: str, since_days: int = 14, max_pages: int = 3) -> tuple[dict, list[dict]]:
    """Profile summary plus every post newer than `since_days`, newest first."""
    user = profile(s, username)
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    summary = {
        "username": user.get("username", username),
        "full_name": user.get("full_name"),
        "user_id": user.get("id"),
        "biography": user.get("biography"),
        "followers": (user.get("edge_followed_by") or {}).get("count"),
        "is_private": user.get("is_private"),
        "external_url": user.get("external_url"),
    }
    timeline = user.get("edge_owner_to_timeline_media") or {}
    out = [_from_node(e.get("node") or {}, summary["username"]) for e in timeline.get("edges") or []]
    out = [p for p in out if p]

    # Pinned posts sort first regardless of age, so only stop paginating when
    # the *oldest* post on a page is older than the window.
    page_info = timeline.get("page_info") or {}
    has_next = bool(page_info.get("has_next_page"))
    oldest = min((p["taken_at_ts"] for p in out), default=None)
    pages = 0
    max_id = page_info.get("end_cursor")
    while has_next and summary["user_id"] and pages < max_pages and oldest is not None and oldest >= cutoff.timestamp():
        data = s.get_json(
            f"/api/v1/feed/user/{summary['user_id']}/",
            {"count": 12, "max_id": max_id},
            referer=f"{sess.BASE}/{summary['username']}/",
        )
        items = data.get("items") or []
        page = [_from_item(i, summary["username"]) for i in items]
        page = [p for p in page if p]
        out.extend(page)
        pages += 1
        has_next = bool(data.get("more_available")) and bool(data.get("next_max_id"))
        max_id = data.get("next_max_id")
        oldest = min((p["taken_at_ts"] for p in page), default=None)
        if not page:
            break

    seen: set[str] = set()
    kept: list[dict] = []
    for p in out:
        if p["code"] in seen:
            continue
        seen.add(p["code"])
        if p["taken_at_ts"] >= cutoff.timestamp() or p.get("pinned"):
            kept.append(p)
    kept.sort(key=lambda p: p["taken_at_ts"], reverse=True)
    for p in kept:
        p.pop("taken_at_ts", None)
    return summary, kept


def _base(username: str, code: str, ts: int) -> dict:
    local = datetime.fromtimestamp(ts).astimezone()
    return {
        "id": f"ig-{code}",
        "account": username,
        "code": code,
        "url": f"{sess.BASE}/p/{code}/",
        "taken_at": local.isoformat(timespec="minutes"),
        "taken_at_ts": ts,
    }


def _from_node(n: dict, username: str) -> dict | None:
    code = n.get("shortcode")
    ts = n.get("taken_at_timestamp")
    if not code or not ts:
        return None
    rec = _base(username, code, int(ts))
    rec["owner"] = ((n.get("owner") or {}).get("username")) or None
    rec["coauthors"] = [c.get("username") for c in n.get("coauthor_producers") or [] if c.get("username")]
    cap_edges = (n.get("edge_media_to_caption") or {}).get("edges") or []
    rec["caption"] = (cap_edges[0].get("node") or {}).get("text", "") if cap_edges else ""
    rec["alt_text"] = n.get("accessibility_caption") or ""
    rec["is_video"] = bool(n.get("is_video"))
    rec["pinned"] = bool(n.get("pinned_for_users"))
    loc = n.get("location") or {}
    rec["location"] = loc.get("name") if loc else None
    images = []
    children = (n.get("edge_sidecar_to_children") or {}).get("edges") or []
    if children:
        for c in children:
            cn = c.get("node") or {}
            if cn.get("display_url"):
                images.append(cn["display_url"])
            if cn.get("accessibility_caption") and cn["accessibility_caption"] not in rec["alt_text"]:
                rec["alt_text"] = (rec["alt_text"] + " | " + cn["accessibility_caption"]).strip(" |")
    elif n.get("display_url"):
        images.append(n["display_url"])
    rec["images"] = images
    rec["likes"] = (n.get("edge_liked_by") or n.get("edge_media_preview_like") or {}).get("count")
    return rec


def _from_item(i: dict, username: str) -> dict | None:
    code = i.get("code")
    ts = i.get("taken_at")
    if not code or not ts:
        return None
    rec = _base(username, code, int(ts))
    rec["owner"] = ((i.get("user") or i.get("owner") or {}).get("username")) or None
    rec["coauthors"] = [c.get("username") for c in i.get("coauthor_producers") or [] if c.get("username")]
    rec["caption"] = ((i.get("caption") or {}).get("text")) or ""
    rec["alt_text"] = i.get("accessibility_caption") or ""
    rec["is_video"] = i.get("media_type") == 2
    rec["pinned"] = bool(i.get("timeline_pinned_user_ids"))
    loc = i.get("location") or {}
    rec["location"] = loc.get("name") if loc else None
    images = []
    for child in i.get("carousel_media") or [i]:
        cands = ((child.get("image_versions2") or {}).get("candidates")) or []
        if cands:
            images.append(cands[0].get("url"))
        ac = child.get("accessibility_caption")
        if ac and ac not in rec["alt_text"]:
            rec["alt_text"] = (rec["alt_text"] + " | " + ac).strip(" |")
    rec["images"] = [u for u in images if u]
    rec["likes"] = i.get("like_count")
    return rec


# ---- generic extraction for the browser transport -------------------------
# The page fetches profile and timeline data from whichever endpoint the
# current front end uses; the shapes below are stable even when URLs move.

def _walk(obj, depth: int = 0):
    if depth > 40:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, depth + 1)


TIMELINE_MARK = "xdt_api__v1__feed__user_timeline"
NOISE_MARKS = ("xdt_api__v1__feed__timeline__connection", "xdt_api__v1__feed__reels_tray", "xdt_api__v1__discover__chaining")


def classify_payload(payload) -> str:
    """'timeline' = the account's own grid query (trust every post in it);
    'noise' = the home-feed prefetch, stories tray, or suggested accounts
    (never the account's posts); 'other' = embedded route data etc., where
    posts must pass the owner/coauthor check."""
    raw = json.dumps(payload)[:200_000] if not isinstance(payload, str) else payload
    if TIMELINE_MARK in raw:
        return "timeline"
    if any(m in raw for m in NOISE_MARKS):
        return "noise"
    return "other"


def belongs_to(rec: dict, username: str) -> bool:
    u = username.lower()
    if (rec.get("owner") or "").lower() == u:
        return True
    return u in [c.lower() for c in rec.get("coauthors") or []]


def extract_posts(payloads: list, username: str) -> list[dict]:
    """Posts that belong on `username`'s grid, from a bag of captured payloads."""
    out: list[dict] = []
    for payload in payloads:
        kind = classify_payload(payload)
        if kind == "noise":
            continue
        for d in _walk(payload):
            if "code" in d and "taken_at" in d and ("caption" in d or "image_versions2" in d or "media_type" in d):
                rec = _from_item(d, username)
            elif "shortcode" in d and "taken_at_timestamp" in d:
                rec = _from_node(d, username)
            else:
                continue
            if rec and (kind == "timeline" or belongs_to(rec, username)):
                out.append(rec)
    return out


def extract_profile(payloads: list, username: str) -> dict:
    for payload in payloads:
        for d in _walk(payload):
            if str(d.get("username", "")).lower() == username.lower() and ("biography" in d or "follower_count" in d or "edge_followed_by" in d):
                return {
                    "username": d.get("username", username),
                    "full_name": d.get("full_name"),
                    "user_id": d.get("id") or d.get("pk"),
                    "biography": d.get("biography"),
                    "followers": d.get("follower_count") or (d.get("edge_followed_by") or {}).get("count"),
                    "is_private": d.get("is_private"),
                    "external_url": d.get("external_url"),
                }
    return {}
