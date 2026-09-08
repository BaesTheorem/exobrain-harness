"""Pure helpers: refs to ids, GraphQL nodes to flat records, and human dates to filter strings.

Nothing here touches the network, so all of it is covered by tests/test_meetupcli.py.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

Json = dict[str, Any]

SITE = "https://www.meetup.com"

_EVENT_URL_RE = re.compile(r"/events/(\d+)")
_SITE_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?meetup\.com/([^/?#]+)", re.IGNORECASE)
# First path segments on meetup.com that are site pages, not group urlnames.
_NOT_GROUPS = {
    "find", "events", "login", "register", "home", "api", "pro", "cities", "topics", "members",
    "messages", "settings", "groups", "start", "help", "blog", "lp", "gql2",
}


def parse_event_ref(ref: str) -> str:
    """An event id from a bare id or any meetup.com event URL."""
    ref = ref.strip()
    if ref.isdigit():
        return ref
    m = _EVENT_URL_RE.search(ref)
    if m:
        return m.group(1)
    raise ValueError(f"not an event id or meetup.com event URL: {ref!r}")


def parse_group_ref(ref: str) -> str:
    """A group urlname from a bare urlname or any meetup.com group URL."""
    ref = ref.strip().strip("/")
    m = _SITE_URL_RE.match(ref)
    if m:
        name = m.group(1)
    elif "/" in ref or " " in ref or not ref:
        raise ValueError(f"not a group urlname or meetup.com group URL: {ref!r}")
    else:
        name = ref
    if name.lower() in _NOT_GROUPS:
        raise ValueError(f"{name!r} is a meetup.com page, not a group")
    return name


# -- time ------------------------------------------------------------------------------------


def iso(dt: datetime) -> str:
    """ISO-8601 with an explicit offset and no microseconds, the shape the filters accept."""
    return dt.replace(microsecond=0).isoformat()


def parse_when(text: str, tz: ZoneInfo, *, end_of_day: bool = False, now: datetime | None = None) -> datetime:
    """today | tomorrow | +Nd | YYYY-MM-DD | 'YYYY-MM-DD HH:MM' | full ISO, in ``tz``."""
    base = (now or datetime.now(tz)).astimezone(tz)
    t = text.strip()
    low = t.lower()
    day = None
    if low == "now":
        return base
    if low == "today":
        day = base.date()
    elif low == "tomorrow":
        day = base.date() + timedelta(days=1)
    elif re.fullmatch(r"\+(\d+)d", low):
        day = base.date() + timedelta(days=int(low[1:-1]))
    if day is not None:
        dt = datetime(day.year, day.month, day.day, tzinfo=tz)
        return dt.replace(hour=23, minute=59, second=59) if end_of_day else dt
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ValueError(
            f"bad date {text!r}; use YYYY-MM-DD, 'YYYY-MM-DD HH:MM', today, tomorrow, or +Nd"
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    if end_of_day and len(t) == 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def window(
    *,
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> tuple[str | None, str | None]:
    """(startDateRange, endDateRange) filter strings. ``days`` counts from ``start`` or now."""
    base = (now or datetime.now(tz)).astimezone(tz)
    s = parse_when(start, tz, now=base) if start else None
    e = parse_when(end, tz, end_of_day=True, now=base) if end else None
    if days is not None:
        anchor = s or base
        s = anchor
        e = (anchor + timedelta(days=days)).replace(hour=23, minute=59, second=59, microsecond=0)
    return (iso(s) if s else None, iso(e) if e else None)


# -- normalization ---------------------------------------------------------------------------


def group_url(urlname: str | None) -> str | None:
    return f"{SITE}/{urlname}/" if urlname else None


def normalize_event(n: Json) -> Json:
    """Flatten an Event node into the record the CLI prints and emits as JSON."""
    v = n.get("venue") or {}
    online = bool(n.get("isOnline")) or v.get("venueType") == "online"
    venue = None
    if v and not online:
        venue = {k: v.get(k) for k in ("id", "name", "address", "city", "state", "postalCode", "country", "lat", "lon")}
    fee = n.get("feeSettings")
    g = n.get("group") or {}
    rec: Json = {
        "id": n.get("id"),
        "title": n.get("title"),
        "start": n.get("dateTime"),
        "end": n.get("endTime"),
        "duration": n.get("duration"),
        "url": n.get("eventUrl"),
        "status": n.get("status"),
        "rsvpState": n.get("rsvpState"),
        "type": (n.get("eventType") or "").lower() or None,
        "online": online,
        "going": (n.get("going") or {}).get("totalCount"),
        "maxTickets": n.get("maxTickets") or None,
        "fee": {"amount": fee.get("amount"), "currency": fee.get("currency")} if fee else None,
        "free": fee is None,
        "venue": venue,
        "group": {
            "id": g.get("id"),
            "name": g.get("name"),
            "urlname": g.get("urlname"),
            "url": group_url(g.get("urlname")),
        } if g else None,
    }
    for key in ("description", "howToFindUs", "isAttending", "isSaved", "myRsvp", "myGuests", "shortUrl"):
        if key in n:
            rec[key] = n[key]
    if "eventHosts" in n:
        rec["hosts"] = [h.get("name") for h in (n.get("eventHosts") or []) if h and h.get("name")]
    if "topics" in n:
        rec["topics"] = [t["node"]["name"] for t in ((n.get("topics") or {}).get("edges") or []) if t.get("node")]
    if "series" in n:
        rec["series"] = (n.get("series") or {}).get("description")
    if "waitlist" in n:
        rec["waitlist"] = (n.get("waitlist") or {}).get("totalCount")
    return rec


def normalize_group(n: Json) -> Json:
    """Flatten a Group node. Upcoming/past connections are folded in when present."""
    stats = (n.get("stats") or {}).get("eventRatings") or {}
    rec: Json = {
        "id": n.get("id"),
        "name": n.get("name"),
        "urlname": n.get("urlname"),
        "url": group_url(n.get("urlname")),
        "city": n.get("city"),
        "state": n.get("state"),
        "country": n.get("country"),
        "timezone": n.get("timezone"),
        "members": (n.get("memberships") or {}).get("totalCount"),
        "private": n.get("isPrivate"),
        "joinMode": n.get("joinMode"),
        "status": n.get("status"),
        "founded": n.get("foundedDate"),
        "rating": stats.get("average"),
        "ratings": stats.get("totalRatings"),
        "category": (n.get("topicCategory") or {}).get("name"),
        "link": n.get("link") or None,
        "isMember": n.get("isMember"),
    }
    for key in ("description", "lat", "lon", "zip", "myRole", "myStatus"):
        if key in n:
            rec[key] = n[key]
    if "activeTopics" in n:
        rec["topics"] = [t.get("name") for t in (n.get("activeTopics") or []) if t]
    if "organizer" in n:
        rec["organizer"] = (n.get("organizer") or {}).get("name")
    if "upcoming" in n:
        up = n.get("upcoming") or {}
        rec["upcomingCount"] = up.get("totalCount")
        rec["upcoming"] = [normalize_event(e["node"]) for e in up.get("edges") or [] if e.get("node")]
    if "past" in n:
        past = n.get("past") or {}
        rec["pastCount"] = past.get("totalCount")
        last = [e["node"] for e in past.get("edges") or [] if e.get("node")]
        rec["lastEvent"] = {"id": last[0].get("id"), "title": last[0].get("title"), "start": last[0].get("dateTime")} if last else None
    return rec

# -- payments --------------------------------------------------------------------------------

# Meetup bills through Taxamo, whose hosted invoice carries fields the GraphQL record does not:
# the human invoice number, the period the payment covers, and the order date. The page is plain
# HTML, so the parse is a handful of anchored regexes over the tag-stripped text. Amounts appear
# in two shapes depending on the invoice's vintage: "US$ 98.94" on the old ones, "98.94 USD" on
# the new.
_MONEY = r"(?:US\$\s*([\d,]+\.\d\d)|([\d,]+\.\d\d)\s*USD)"
_INV_FIELDS = {
    "invoiceNo": r"Invoice # ?: ([A-Za-z0-9\-]+)",
    "billingCycle": r"Billing cycle: (.+?) Order date:",
    "orderDate": r"Order date: (.+?) Order number:",
    "orderNumber": r"Order number: ([A-Za-z0-9\-]+)",
    "product": r"Summary Meetup Meetup (Subscription: .+?)\s+(?:US\$|[\d,]+\.\d\d\s*USD)",
}


def invoice_text(page: str) -> str:
    """Tag-stripped, whitespace-collapsed text of a Taxamo invoice page."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)).replace("\xa0", " ")).strip()


def parse_invoice(page: str) -> Json:
    """The fields Meetup's hosted invoice adds on top of the payment record."""
    text = invoice_text(page)
    out: Json = {k: (m.group(1).strip() if (m := re.search(p, text)) else None)
                 for k, p in _INV_FIELDS.items()}

    def money(pattern: str) -> float | None:
        m = re.search(pattern, text)
        return float((m.group(1) or m.group(2)).replace(",", "")) if m else None

    out["total"] = money(r"Total\s+" + _MONEY)
    out["discount"] = money(r"Discount\s*\(\s*" + _MONEY + r"\s*\)")
    return out


def normalize_payment(n: Json) -> Json:
    """A paid invoice, flattened. ``amount`` is dollars; the API reports cents."""
    cents = n.get("amount")
    return {
        "id": n.get("id"),
        "date": (n.get("creationDate") or "")[:10] or None,
        "creationDate": n.get("creationDate"),
        "amount": round(cents / 100, 2) if isinstance(cents, int) else None,
        "currency": n.get("currency"),
        "orderNumber": n.get("invoiceNumber"),
        "status": n.get("status"),
        "url": n.get("url"),
    }
