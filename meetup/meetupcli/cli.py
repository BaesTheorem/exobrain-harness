"""Command-line front end for the meetup.com client.

Human-readable output by default; ``--json`` emits the normalized records instead so the
output can feed other tools (the local-events skill reads it). ``raw`` is the escape hatch
for any GraphQL operation the named commands do not cover.

Exit status: 0 ok, 1 server/transport error, 2 usage error, 3 login needed or rejected.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import textwrap
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from meetupcli import store
from meetupcli.api import MeetupClient, MeetupError
from meetupcli.model import (
    normalize_event,
    normalize_group,
    normalize_payment,
    parse_event_ref,
    parse_group_ref,
    parse_invoice,
    window,
)

Json = dict[str, Any]

EVENT_TYPES = {"physical": "PHYSICAL", "online": "ONLINE", "hybrid": "HYBRID"}
SORTS = {"date": "DATETIME", "relevance": "RELEVANCE"}
WRAP = 88


# -- formatting ------------------------------------------------------------------------------


def fmt_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_when(iso_s: str | None) -> str:
    if not iso_s:
        return "?"
    try:
        dt = datetime.fromisoformat(iso_s)
    except ValueError:
        return iso_s
    return f"{dt:%a %b} {dt.day}, {fmt_time(dt)}"


def fmt_span(start: str | None, end: str | None) -> str:
    if not start:
        return "?"
    try:
        s = datetime.fromisoformat(start)
    except ValueError:
        return start
    out = f"{s:%a %b} {s.day}, {s.year}, {fmt_time(s)}"
    if end:
        try:
            e = datetime.fromisoformat(end)
        except ValueError:
            return out
        out += f" to {fmt_time(e)}" if e.date() == s.date() else f" to {e:%a %b} {e.day}, {fmt_time(e)}"
    return out


def fmt_fee(ev: Json) -> str:
    if ev.get("free"):
        return "free"
    fee = ev.get("fee") or {}
    amount, currency = fee.get("amount"), fee.get("currency")
    if amount is None:
        return "paid"
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"${text}" if currency == "USD" else f"{text} {currency}"


def fmt_where(ev: Json) -> str:
    if ev.get("online"):
        return "Online"
    v = ev.get("venue") or {}
    city = ", ".join(p for p in (v.get("city"), v.get("state")) if p)
    return ", ".join(p for p in (v.get("name"), v.get("address"), city) if p) or "venue not listed"


def wrap(text: str, indent: str = "  ") -> str:
    paras = [p.strip() for p in text.replace("\r", "").split("\n")]
    out = []
    for p in paras:
        out.append(textwrap.fill(p, WRAP, initial_indent=indent, subsequent_indent=indent) if p else "")
    return "\n".join(out).strip("\n")


def emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def print_events(events: list[Json], header: str | None = None) -> None:
    if header:
        print(header)
    if not events:
        print("  (no events)")
        return
    for ev in events:
        flags = []
        my = ev.get("myRsvp")
        over = ev.get("status") == "PAST"
        guests = f" +{ev['myGuests']}" if ev.get("myGuests") else ""
        if my == "ATTENDED" or (over and my == "YES"):
            flags.append("you went" + guests)
        elif ev.get("isAttending") or my in ("YES", "YES_PENDING_PAYMENT"):
            flags.append("you're going" + guests)
        elif my == "WAITLIST":
            flags.append("waitlisted")
        elif my == "NO_SHOW":
            flags.append("no-show")
        if ev.get("isSaved"):
            flags.append("saved")
        if ev.get("status") and ev["status"] not in ("ACTIVE", "PAST"):
            flags.append(str(ev["status"]))
        going = ev.get("going")
        meta = [
            (ev.get("group") or {}).get("name"),
            fmt_where(ev),
            f"{going} going" if going is not None else None,
            fmt_fee(ev),
            ev.get("url"),
        ]
        title = ev.get("title") or ""
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{str(ev.get('id') or ''):<10} {fmt_when(ev.get('start')):<21} {title}{suffix}")
        print(f"{'':<32} {' · '.join(m for m in meta if m)}")


def print_event(ev: Json) -> None:
    print(ev.get("title") or "(untitled)")
    print(f"  When:    {fmt_span(ev.get('start'), ev.get('end'))}")
    print(f"  Where:   {fmt_where(ev)}")
    v = ev.get("venue") or {}
    if v.get("lat") is not None and v.get("lon") is not None:
        print(f"           https://www.google.com/maps/search/?api=1&query={v['lat']},{v['lon']}")
    g = ev.get("group") or {}
    if g:
        print(f"  Group:   {g.get('name')} · {g.get('url')}")
    rsvps = [f"{ev['going']} going" if ev.get("going") is not None else None]
    if ev.get("waitlist"):
        rsvps.append(f"{ev['waitlist']} waitlisted")
    if ev.get("maxTickets"):
        rsvps.append(f"{ev['maxTickets']} spots")
    print(f"  RSVPs:   {' · '.join(r for r in rsvps if r) or '?'}")
    print(f"  Cost:    {fmt_fee(ev)}")
    status = [str(ev.get("status") or "?").lower(), f"rsvp {str(ev.get('rsvpState') or '?').lower().replace('_', ' ')}"]
    if ev.get("isAttending"):
        status.append("you're going")
    if ev.get("isSaved"):
        status.append("saved")
    print(f"  Status:  {' · '.join(status)}")
    if ev.get("hosts"):
        print(f"  Hosts:   {', '.join(ev['hosts'])}")
    if ev.get("series"):
        print(f"  Series:  {ev['series']}")
    if ev.get("topics"):
        print(f"  Topics:  {', '.join(ev['topics'])}")
    print(f"  URL:     {ev.get('url')}")
    if ev.get("howToFindUs"):
        print("  How to find us:")
        print(wrap(ev["howToFindUs"], "    "))
    if ev.get("description"):
        print()
        print(wrap(ev["description"]))


def print_groups(groups: list[Json], header: str | None = None) -> None:
    if header:
        print(header)
    if not groups:
        print("  (no groups)")
        return
    for g in groups:
        bits = [
            ", ".join(p for p in (g.get("city"), g.get("state")) if p),
            f"{g['members']:,} members" if g.get("members") is not None else None,
            f"rated {g['rating']:.1f} ({g.get('ratings')})" if g.get("rating") else None,
            "private" if g.get("private") else None,
            str(g["myRole"]).lower().replace("_", " ") if g.get("myRole") else ("member" if g.get("isMember") else None),
            str(g["myStatus"]).lower().replace("_", " ") if g.get("myStatus") not in (None, "ACTIVE", "LEADER") else None,
            g.get("url"),
        ]
        print(f"{str(g.get('id') or ''):<10} {g.get('name')}  ({g.get('urlname')})")
        print(f"{'':<10} {' · '.join(b for b in bits if b)}")


def print_group(g: Json) -> None:
    print(f"{g.get('name')}  ({g.get('urlname')})")
    print(f"  URL:      {g.get('url')}")
    where = ", ".join(p for p in (g.get("city"), g.get("state")) if p)
    facts = [
        where or None,
        g.get("category"),
        f"{g['members']:,} members" if g.get("members") is not None else None,
        f"rated {g['rating']:.2f} over {g.get('ratings')} ratings" if g.get("rating") else None,
        "private" if g.get("private") else "public",
        f"join: {str(g.get('joinMode') or '?').lower()}",
        f"since {str(g.get('founded'))[:10]}" if g.get("founded") else None,
    ]
    print(f"  About:    {' · '.join(f for f in facts if f)}")
    if g.get("organizer"):
        print(f"  Organizer: {g['organizer']}")
    if g.get("isMember"):
        print(f"  You:      member{(' (' + str(g['myRole']).lower() + ')') if g.get('myRole') else ''}")
    if g.get("topics"):
        print(f"  Topics:   {', '.join(t for t in g['topics'] if t)}")
    if g.get("link"):
        print(f"  Website:  {g['link']}")
    if g.get("lastEvent"):
        last = g["lastEvent"]
        print(f"  Last met: {fmt_when(last.get('start'))} · {last.get('title')} ({g.get('pastCount')} past events)")
    if "upcoming" in g:
        print()
        print_events(g.get("upcoming") or [], header=f"Upcoming ({g.get('upcomingCount')} scheduled):")
    if g.get("description"):
        print()
        print(wrap(g["description"]))


# -- plumbing --------------------------------------------------------------------------------


def make_client() -> MeetupClient:
    return MeetupClient(cookie=store.load_cookie())


def tz() -> ZoneInfo:
    return ZoneInfo(store.timezone_name())


def resolve_location(client: MeetupClient, args: argparse.Namespace) -> tuple[float, float, str]:
    """(lat, lon, label) from --lat/--lon, --near, or the home default."""
    lat, lon = getattr(args, "lat", None), getattr(args, "lon", None)
    if (lat is None) != (lon is None):
        raise ValueError("--lat and --lon go together")
    if lat is not None and lon is not None:
        return lat, lon, f"{lat},{lon}"
    near = getattr(args, "near", None)
    if near:
        hits = client.location_search(near)
        if not hits:
            raise MeetupError(f"Meetup has no location matching {near!r}")
        hit = hits[0]
        return float(hit["lat"]), float(hit["lon"]), str(hit.get("name") or near)
    label, lat, lon = store.home_location()
    return lat, lon, label


def window_from(args: argparse.Namespace, default_days: int | None = None) -> tuple[str | None, str | None]:
    days = args.days if args.days is not None else (default_days if not (args.start or args.end) else None)
    return window(days=days, start=args.start, end=args.end, tz=tz())


def describe_window(args: argparse.Namespace, start: str | None, end: str | None) -> str:
    if args.days is not None and not args.start:
        return f"next {args.days} day{'s' if args.days != 1 else ''}"
    if start and end:
        return f"{start[:10]} to {end[:10]}"
    if start:
        return f"from {start[:10]}"
    if end:
        return f"through {end[:10]}"
    return "upcoming"


def confirm(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise MeetupError("refusing to change an RSVP non-interactively without --yes")
    answer = input(f"{prompt} [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise MeetupError("cancelled")


# -- commands --------------------------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    client = make_client()
    lat, lon, label = resolve_location(client, args)
    start, end = window_from(args)
    nodes = client.event_search(
        query, lat, lon,
        radius=args.radius, start=start, end=end,
        event_type=EVENT_TYPES[args.type] if args.type else None,
        sort=SORTS[args.sort], limit=args.limit,
    )
    events = [normalize_event(n) for n in nodes]
    if args.free:
        events = [e for e in events if e["free"]]
    if args.json:
        emit_json(events)
        return 0
    radius = f" within {args.radius:g} mi" if args.radius else ""
    print_events(events, header=f"{len(events)} events for {query!r} near {label}{radius}, {describe_window(args, start, end)}, by {args.sort}:")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    client = make_client()
    lat, lon, label = resolve_location(client, args)
    start, end = window_from(args, default_days=7)
    nodes = client.recommended_events(
        lat, lon,
        radius=args.radius, start=start, end=end,
        event_type=EVENT_TYPES[args.type] if args.type else None,
        sort=SORTS[args.sort], limit=args.limit,
    )
    events = [normalize_event(n) for n in nodes]
    if args.free:
        events = [e for e in events if e["free"]]
    if args.json:
        emit_json(events)
        return 0
    radius = f" within {args.radius:g} mi" if args.radius else ""
    print_events(events, header=f"{len(events)} events near {label}{radius}, {describe_window(args, start, end)}:")
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    ids = [parse_event_ref(r) for r in args.ref]
    client = make_client()
    nodes = client.events(ids)
    found = {n["id"]: n for n in nodes}
    missing = [i for i in ids if i not in found]
    if missing:
        print(f"meetup: no event with id {', '.join(missing)} (deleted, draft, or private)", file=sys.stderr)
    events = [normalize_event(found[i]) for i in ids if i in found]
    if args.json:
        emit_json(events[0] if len(ids) == 1 and events else events)
    else:
        for n, ev in enumerate(events):
            if n:
                print("\n" + "-" * WRAP)
            print_event(ev)
    if args.similar and events:
        similar = [normalize_event(s) for s in client.similar_events(events[0]["id"], limit=args.similar)]
        if args.json:
            emit_json(similar)
        else:
            print()
            print_events(similar, header="Similar events:")
    return 0 if events else 1


def cmd_group(args: argparse.Namespace) -> int:
    name = parse_group_ref(args.ref)
    node = make_client().group(name, upcoming=args.upcoming)
    if not node:
        raise MeetupError(f"no group with urlname {name!r}")
    g = normalize_group(node)
    if args.json:
        emit_json(g)
    else:
        print_group(g)
    return 0


def cmd_group_events(args: argparse.Namespace) -> int:
    name = parse_group_ref(args.ref)
    nodes = make_client().group_events(name, past=args.past, limit=args.limit)
    events = [normalize_event(n) for n in nodes]
    if args.json:
        emit_json(events)
    else:
        print_events(events, header=f"{'Past' if args.past else 'Upcoming'} events for {name}:")
    return 0


def cmd_groups(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    client = make_client()
    lat, lon, label = resolve_location(client, args)
    nodes = client.group_search(query, lat, lon, radius=args.radius, limit=args.limit)
    groups = [normalize_group(n) for n in nodes]
    if args.json:
        emit_json(groups)
    else:
        print_groups(groups, header=f"{len(groups)} groups for {query!r} near {label}:")
    return 0


def cmd_locations(args: argparse.Namespace) -> int:
    hits = make_client().location_search(" ".join(args.query))
    if args.json:
        emit_json(hits)
        return 0
    if not hits:
        print("  (no matches)")
        return 1
    for h in hits:
        print(f"{h.get('name'):<36} {h.get('lat'):>10.4f} {h.get('lon'):>10.4f}  {h.get('zip') or '':<8} {h.get('timeZone') or ''}")
    return 0


def cmd_home(args: argparse.Namespace) -> int:
    label, lat, lon = store.home_location()
    if args.json:
        emit_json({"label": label, "lat": lat, "lon": lon, "timezone": store.timezone_name()})
    else:
        print(f"{label}  {lat},{lon}  {store.timezone_name()}  (override with MEETUP_HOME='lat,lon,label' and MEETUP_TZ)")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    me = make_client().self_member()
    if args.json:
        emit_json(me)
        return 0
    roles = [r for r, on in (("organizer", me.get("isOrganizer")), ("pro organizer", me.get("isProOrganizer"))) if on]
    where = ", ".join(p for p in (me.get("city"), me.get("state")) if p)
    bits = [f"member {me.get('id')}", where or None, ", ".join(roles) or None, f"organizes {me.get('organizedGroupCount')} group(s)" if me.get("organizedGroupCount") else None, me.get("memberUrl")]
    print(f"{me.get('name')} · {' · '.join(b for b in bits if b)}")
    return 0


def cmd_my_events(args: argparse.Namespace) -> int:
    events = [normalize_event(n) for n in make_client().my_events(past=args.past, limit=args.limit)]
    if args.json:
        emit_json(events)
    else:
        print_events(events, header="Events you went to (newest first):" if args.past else "Your upcoming RSVPs:")
    return 0


def cmd_my_calendar(args: argparse.Namespace) -> int:
    events = [normalize_event(n) for n in make_client().my_calendar(limit=args.limit)]
    if args.json:
        emit_json(events)
    else:
        print_events(events, header="Upcoming events in your groups (RSVP'd or not):")
    return 0


def cmd_my_groups(args: argparse.Namespace) -> int:
    groups = [normalize_group(n) for n in make_client().my_groups(limit=args.limit, include_inactive=args.all)]
    if args.json:
        emit_json(groups)
    else:
        print_groups(groups, header="All memberships, including dead and blocked groups:" if args.all else "Your groups:")
    return 0


def cmd_payments(args: argparse.Namespace) -> int:
    client = make_client()
    rows = [normalize_payment(n) for n in client.payments(limit=args.limit, lane=args.lane)]
    if args.invoices:
        for row in rows:
            if row["url"]:
                row.update(parse_invoice(client.invoice_page(row["url"])))
    if args.since:
        rows = [r for r in rows if (r["date"] or "") >= args.since]

    if args.json:
        emit_json(rows)
        return 0
    if not rows:
        print("No payments on this account.")
        return 0

    print("Paid Meetup invoices, oldest first:\n")
    for r in rows:
        amount = f"${r['amount']:,.2f}" if r["amount"] is not None else "?"
        line = f"  {r['date'] or '?':<11} {amount:>10}  {r['orderNumber'] or ''}"
        if r.get("invoiceNo"):
            line += f"  invoice {r['invoiceNo']}"
        print(line)
        if r.get("billingCycle"):
            covers = f"covers {r['billingCycle']}"
            if r.get("product"):
                covers += f" ({r['product']})"
            print(f"              {covers}")
        if r.get("discount"):
            print(f"              discount of ${r['discount']:,.2f} applied")
    total = sum(r["amount"] or 0 for r in rows)
    print(f"\n  {len(rows)} payment(s), ${total:,.2f} total")
    return 0


def cmd_rsvp(args: argparse.Namespace) -> int:
    event_id = parse_event_ref(args.ref)
    going = args.answer == "yes"
    client = make_client()
    node = client.event(event_id)
    if not node:
        raise MeetupError(f"no event with id {event_id}")
    ev = normalize_event(node)
    print(f"{ev['title']} · {fmt_when(ev['start'])} · {fmt_where(ev)} · {fmt_fee(ev)}")
    guests = f" plus {args.guests} guest(s)" if args.guests else ""
    confirm(f"RSVP {args.answer.upper()}{guests}?", args.yes)
    result = client.rsvp(event_id, going, guests=args.guests)
    if args.json:
        emit_json(result)
        return 0
    rsvp = result.get("rsvp") or {}
    print(f"RSVP recorded: {str(rsvp.get('status') or args.answer).lower()}"
          + (f", {rsvp['guestsCount']} guest(s)" if rsvp.get("guestsCount") else ""))
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    event_id = parse_event_ref(args.ref)
    result = make_client().save_event(event_id, save=not args.unsave)
    if args.json:
        emit_json(result)
    else:
        saved = (result.get("event") or {}).get("isSaved")
        print(f"event {event_id} {'saved' if saved else 'unsaved'}")
    return 0


def cmd_venues(args: argparse.Namespace) -> int:
    client = make_client()
    lat, lon, label = resolve_location(client, args)
    rows = client.suggest_venues(" ".join(args.query), lat, lon,
                                 radius=args.radius or 25.0, limit=args.limit)
    if args.json:
        emit_json(rows)
        return 0
    print(f"{len(rows)} venue(s) near {label}:")
    for v in rows:
        where = ", ".join(x for x in (v.get("address"), v.get("city"), v.get("state")) if x)
        print(f"  {v['id']:12} {v.get('name')}  |  {where} {v.get('postalCode') or ''}".rstrip())
    if rows:
        print("\n  Meetup's venue records are member-entered and can be stale: check the address\n"
              "  against the real one before using an id, and prefer `create-venue` when it differs.")
    return 0


def cmd_create_venue(args: argparse.Namespace) -> int:
    result = make_client().create_venue(args.name, args.address, args.city, args.state,
                                        country=args.country, group_id=args.group_id)
    if args.json:
        emit_json(result)
        return 0
    v = result.get("venue") or {}
    print(f"venue {v.get('id')}: {v.get('name')} | {v.get('address')}, {v.get('city')} {v.get('state')}")
    for d in result.get("didYouMean") or []:
        print(f"  did you mean {d.get('id')}: {d.get('name')} | {d.get('address')}")
    return 0


def cmd_create_event(args: argparse.Namespace) -> int:
    description = Path(args.desc_file).read_text() if args.desc_file else args.desc
    if not description:
        raise MeetupError("an event needs a description: pass --desc or --desc-file")
    if args.publish:
        print(f"{args.title} · {args.start} · group {args.group}")
        confirm("PUBLISH this event now? Members of the group can see published events.", args.yes)
    result = make_client().create_event(
        args.group, args.title, description, args.start,
        duration=args.duration, venue_id=args.venue,
        how_to_find_us=args.how_to_find_us, publish=args.publish,
    )
    if args.json:
        emit_json(result)
        return 0
    ev = result.get("event") or {}
    print(f"{str(ev.get('status') or '?').lower()}: {ev.get('title')} · {ev.get('dateTime')} · {ev.get('eventUrl')}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    event_id = parse_event_ref(args.ref)
    client = make_client()
    node = client.event(event_id)
    if node:
        ev = normalize_event(node)
        print(f"{ev['title']} · {fmt_when(ev['start'])} · {fmt_where(ev)}")
    confirm("Publish this draft? It becomes visible to the whole group.", args.yes)
    result = client.publish_draft(event_id)
    if args.json:
        emit_json(result)
        return 0
    ev = result.get("event") or {}
    print(f"published: {ev.get('title')} · {ev.get('eventUrl')}")
    return 0


def cmd_delete_event(args: argparse.Namespace) -> int:
    event_id = parse_event_ref(args.ref)
    confirm(f"Delete event {event_id}?", args.yes)
    result = make_client().delete_event(event_id, series=args.series)
    if args.json:
        emit_json(result)
    else:
        print(f"event {event_id} deleted" if result.get("success") else f"delete returned {result}")
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    if args.action == "clear":
        print("cookie removed" if store.clear_cookie() else "no stored cookie")
        return 0
    if args.action == "import":
        try:
            header = store.import_cookie_from_browser(args.browser)
        except RuntimeError as e:
            raise MeetupError(str(e), auth=True) from None
        path = store.save_cookie(header)
        print(f"imported {header.count('=')} meetup.com cookies from {args.browser} into {path} (mode 0600)")
    if args.action == "set":
        if args.from_file:
            text = open(args.from_file, encoding="utf-8").read()
        else:
            if sys.stdin.isatty():
                print("Paste the Cookie header from a logged-in meetup.com request, then press Enter:", file=sys.stderr)
            text = sys.stdin.readline()
        path = store.save_cookie(text)
        print(f"stored in {path} (mode 0600)")
    source = store.cookie_source()
    if not source:
        print("no cookie: `meetup auth set` (see meetup/secrets/README.md)")
        return 3
    print(f"cookie source: {source}")
    try:
        me = MeetupClient(cookie=store.load_cookie()).self_member()
    except MeetupError as e:
        print(f"check failed: {e}")
        return 3 if e.auth else 1
    print(f"logged in as {me.get('name')} (member {me.get('id')})")
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    query = sys.stdin.read() if args.query == "-" else args.query
    variables = json.loads(args.vars) if args.vars else {}
    client = make_client()
    data = client.gql(query, variables, authed=args.authed)
    if client.last_errors:
        print(json.dumps(client.last_errors, indent=2), file=sys.stderr)
    emit_json(data)
    return 0


# -- parser ----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit normalized JSON instead of text")

    location = argparse.ArgumentParser(add_help=False)
    location.add_argument("--near", metavar="PLACE", help="city or place name, resolved by Meetup's location search (default: home)")
    location.add_argument("--lat", type=float, help="latitude (with --lon)")
    location.add_argument("--lon", type=float, help="longitude (with --lat)")
    location.add_argument("--radius", type=float, metavar="MILES", help="only events within this many miles")

    when = argparse.ArgumentParser(add_help=False)
    when.add_argument("--days", type=int, metavar="N", help="only events in the next N days")
    when.add_argument("--from", dest="start", metavar="WHEN", help="earliest start: YYYY-MM-DD, 'YYYY-MM-DD HH:MM', today, tomorrow, +Nd")
    when.add_argument("--to", dest="end", metavar="WHEN", help="latest start (same forms; a bare date means end of that day)")
    when.add_argument("--type", choices=sorted(EVENT_TYPES), help="physical, online, or hybrid events only")
    when.add_argument("--free", action="store_true", help="drop events that charge a fee through Meetup")

    p = argparse.ArgumentParser(
        prog="meetup",
        description="Unofficial meetup.com CLI. Searching and reading need no login; personal commands use your browser cookie.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    s = sub.add_parser("search", parents=[common, location, when], help="search upcoming events by keyword")
    s.add_argument("query", nargs="+")
    s.add_argument("--sort", choices=sorted(SORTS), default="relevance")
    s.add_argument("--limit", type=int, default=20, help="max results (0 = all, capped at 500)")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("events", parents=[common, location, when], help="browse upcoming events near a place (default: next 7 days)")
    s.add_argument("--sort", choices=sorted(SORTS), default="date")
    s.add_argument("--limit", type=int, default=30, help="max results (0 = all, capped at 500)")
    s.set_defaults(func=cmd_events)

    s = sub.add_parser("event", parents=[common], help="full details for one or more events (id or URL)")
    s.add_argument("ref", nargs="+", help="event id or meetup.com event URL")
    s.add_argument("--similar", type=int, metavar="N", help="also list N similar events")
    s.set_defaults(func=cmd_event)

    s = sub.add_parser("group", parents=[common], help="a group's profile plus its next events")
    s.add_argument("ref", help="group urlname or meetup.com group URL")
    s.add_argument("--upcoming", type=int, default=5, metavar="N", help="how many upcoming events to show")
    s.set_defaults(func=cmd_group)

    s = sub.add_parser("group-events", parents=[common], help="a group's upcoming (or --past) events")
    s.add_argument("ref", help="group urlname or meetup.com group URL")
    s.add_argument("--past", action="store_true", help="most recent past events instead")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_group_events)

    s = sub.add_parser("groups", parents=[common, location], help="search groups by keyword")
    s.add_argument("query", nargs="+")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_groups)

    s = sub.add_parser("locations", parents=[common], help="resolve a place name to coordinates (what --near uses)")
    s.add_argument("query", nargs="+")
    s.set_defaults(func=cmd_locations)

    s = sub.add_parser("home", parents=[common], help="show the default location and timezone")
    s.set_defaults(func=cmd_home)

    s = sub.add_parser("whoami", parents=[common], help="who the stored cookie logs in as")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("my-events", parents=[common], help="events you RSVP'd to (yes or waitlist)")
    s.add_argument("--past", action="store_true", help="events you went to, newest first")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_my_events)

    s = sub.add_parser("my-calendar", parents=[common], help="upcoming events across your groups, RSVP'd or not")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_my_calendar)

    s = sub.add_parser("my-groups", parents=[common], help="groups you belong to")
    s.add_argument("--all", action="store_true", help="include dead and blocked memberships too")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_my_groups)

    s = sub.add_parser("payments", parents=[common], help="paid invoices on your account")
    s.add_argument("--invoices", action="store_true",
                   help="also fetch each hosted invoice for its number, billing period and total")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only payments on or after this date")
    s.add_argument("--lane", choices=["MEMBER", "ORGANIZER"], help="one subscription lane (default: both)")
    s.add_argument("--limit", type=int, default=200, help="max payments per lane (default 200)")
    s.set_defaults(func=cmd_payments)

    s = sub.add_parser("rsvp", parents=[common], help="RSVP yes or no to an event (asks first)")
    s.add_argument("ref", help="event id or URL")
    s.add_argument("answer", choices=["yes", "no"])
    s.add_argument("--guests", type=int, default=0, help="guests to bring, if the event allows it")
    s.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    s.set_defaults(func=cmd_rsvp)

    s = sub.add_parser("save", parents=[common], help="save (bookmark) an event, or --unsave")
    s.add_argument("ref", help="event id or URL")
    s.add_argument("--unsave", action="store_true")
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("venues", parents=[common, location], help="search Meetup's venue records (organizer use)")
    s.add_argument("query", nargs="+")
    s.set_defaults(func=cmd_venues)

    s = sub.add_parser("create-venue", parents=[common], help="register a venue Meetup does not have, or has stale")
    s.add_argument("--name", required=True)
    s.add_argument("--address", required=True)
    s.add_argument("--city", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--country", default="us")
    s.add_argument("--group-id", dest="group_id", help="scope the venue to one group")
    s.set_defaults(func=cmd_create_venue)

    s = sub.add_parser("create-event", parents=[common],
                       help="create a group event (a DRAFT unless --publish; drafts notify nobody)")
    s.add_argument("group", help="group urlname, e.g. kc_rat_ea")
    s.add_argument("--title", required=True)
    s.add_argument("--start", required=True, metavar="WHEN", help="local start, 'YYYY-MM-DDTHH:MM'")
    s.add_argument("--desc", help="description text")
    s.add_argument("--desc-file", dest="desc_file", help="read the description from a file")
    s.add_argument("--duration", help="ISO-8601 duration, e.g. PT2H")
    s.add_argument("--venue", help="Meetup venue id (see `venues`)")
    s.add_argument("--how-to-find-us", dest="how_to_find_us")
    s.add_argument("--publish", action="store_true", help="publish immediately instead of drafting (asks first)")
    s.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    s.set_defaults(func=cmd_create_event)

    s = sub.add_parser("publish", parents=[common], help="publish a draft event (asks first)")
    s.add_argument("ref", help="event id or URL")
    s.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("delete-event", parents=[common], help="delete an event (asks first)")
    s.add_argument("ref", help="event id or URL")
    s.add_argument("--series", action="store_true", help="delete the whole recurring series")
    s.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    s.set_defaults(func=cmd_delete_event)

    s = sub.add_parser("auth", help="import, paste, check, or clear the login cookie")
    s.add_argument("action", choices=["import", "set", "status", "clear"],
                   help="import = read it out of a browser profile (yt-dlp); set = paste a Cookie header")
    s.add_argument("--browser", default="chrome", choices=store.BROWSERS, help="for import: which browser profile (default chrome)")
    s.add_argument("--from-file", metavar="PATH", help="for set: read the cookie header from a file instead of stdin")
    s.set_defaults(func=cmd_auth)

    s = sub.add_parser("raw", help="run any GraphQL operation against gql2 (prints data as JSON)")
    s.add_argument("query", help="GraphQL document, or - to read it from stdin")
    s.add_argument("--vars", metavar="JSON", help="variables as a JSON object")
    s.add_argument("--authed", action="store_true", help="require the login cookie")
    s.set_defaults(func=cmd_raw)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except MeetupError as e:
        print(f"meetup: {e}", file=sys.stderr)
        return 3 if e.auth else 1
    except (ValueError, json.JSONDecodeError) as e:
        print(f"meetup: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
