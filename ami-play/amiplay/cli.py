"""Command-line front end for the AMI Play client.

Human-readable output by default; ``--json`` dumps the server's response instead so the
output can feed other tools. Exit status: 0 ok, 1 server/transport error, 2 usage error.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from typing import Any

from amiplay.api import DEVICE_TYPE_MUSIC, DEVICE_TYPE_NAMES, ENVIRONMENTS, SELECTION_CODES, AmiClient, AmiError
from amiplay.store import Session

Params = dict[str, Any]


# -- formatting ------------------------------------------------------------------------------


def duration(sec: Any) -> str:
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return ""
    return f"{sec // 60}:{sec % 60:02d}"


def dollars(pennies: Any) -> str:
    try:
        return f"${int(pennies) / 100:,.2f}"
    except (TypeError, ValueError):
        return "?"


def credits_for(jukebox: Params | None, pennies: Any) -> str:
    if not jukebox or not jukebox.get("basePrice"):
        return ""
    try:
        n = int(pennies) // int(jukebox["basePrice"])
    except (TypeError, ValueError, ZeroDivisionError):
        return ""
    return f"{n} credit{'s' if n != 1 else ''}"


def table(rows: list[list[Any]], headers: list[str] | None = None) -> str:
    if not rows and not headers:
        return ""
    cells = [[str(c) if c is not None else "" for c in r] for r in rows]
    if headers:
        cells.insert(0, headers)
    widths = [max(len(r[i]) if i < len(r) else 0 for r in cells) for i in range(max(len(r) for r in cells))]
    lines = []
    for n, r in enumerate(cells):
        lines.append("  ".join((r[i] if i < len(r) else "").ljust(widths[i]) for i in range(len(widths))).rstrip())
        if headers and n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def song_row(s: Params, jukebox: Params | None = None) -> list[Any]:
    flags = ("E" if s.get("explicit") else "") + ("L" if s.get("local") else "") + ("X" if s.get("blocked") else "")
    return [s.get("songId") or s.get("id"), s.get("songTitle") or s.get("title"), s.get("artistName"), s.get("albumName"), duration(s.get("durationSec")), flags]


SONG_HEADERS = ["songId", "title", "artist", "album", "len", "flags"]


def venue_row(v: Params) -> list[Any]:
    kinds = []
    for d in v.get("devices") or []:
        name = DEVICE_TYPE_NAMES.get(d.get("deviceType"), str(d.get("deviceType")))
        kinds.append(name if not d.get("count") or d["count"] == 1 else f"{name}x{d['count']}")
    dist = v.get("distance")
    dist_s = f"{dist:.1f} mi" if isinstance(dist, (int, float)) and dist > 0 else ""
    marks = ("*" if v.get("isFavorite") else "") + ("" if v.get("canInteract", True) else "!")
    return [v.get("id"), v.get("name"), f"{v.get('city', '')}, {v.get('state', '')}", dist_s, ",".join(kinds), marks]


VENUE_HEADERS = ["id", "venue", "city", "dist", "devices", ""]


def emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


# -- venue / jukebox resolution --------------------------------------------------------------


def jukebox_of(venue: Params) -> Params | None:
    for d in venue.get("devices") or []:
        if d.get("deviceType") == DEVICE_TYPE_MUSIC and d.get("deviceId") is not None:
            return d
    return None


def remember_venue(session: Session, venue: Params) -> Params | None:
    jb = jukebox_of(venue)
    session.checked_in = {
        "id": venue["id"],
        "name": venue.get("name"),
        "deviceId": jb.get("deviceId") if jb else None,
        "deviceType": jb.get("deviceType") if jb else None,
        "basePrice": jb.get("basePrice") if jb else None,
        "geocode": venue.get("geocode"),
    }
    session.save()
    return jb


def resolve_venue(client: AmiClient, args: argparse.Namespace, fresh: bool = False) -> tuple[Params, Params | None]:
    """(venue detail, jukebox device). ``--venue ID`` wins; otherwise the checked-in venue."""
    venue_id = getattr(args, "venue", None)
    cached = client.session.checked_in
    if venue_id is None:
        if not cached:
            raise AmiError(None, "no venue: pass --venue ID or check in with `ami-play checkin ID`")
        venue_id = cached["id"]
        if not fresh and cached.get("deviceId") is not None:
            venue = {"id": cached["id"], "name": cached.get("name"), "geocode": cached.get("geocode")}
            return venue, {"deviceId": cached["deviceId"], "deviceType": cached.get("deviceType"), "basePrice": cached.get("basePrice")}
    venue = client.venue(int(venue_id))
    return venue, jukebox_of(venue)


def parse_geocode(spec: str | None, session: Session, venue: Params | None = None) -> dict[str, float] | None:
    if spec is None:
        return session.geocode
    spec = spec.strip().lower()
    if spec == "venue":
        if not venue or not venue.get("geocode"):
            raise AmiError(None, "--at venue needs a venue with a geocode")
        return {"lat": float(venue["geocode"]["lat"]), "lng": float(venue["geocode"]["lng"])}
    if spec in ("none", "off"):
        return None
    try:
        lat, lng = (float(p) for p in spec.split(","))
    except ValueError:
        raise AmiError(None, f"--at wants LAT,LNG (or 'venue'), got {spec!r}") from None
    geo = {"lat": lat, "lng": lng}
    session.geocode = geo
    session.save()
    return geo


# -- commands --------------------------------------------------------------------------------


def cmd_login(client: AmiClient, args: argparse.Namespace) -> int:
    email = args.email or client.session.data.get("email") or input("AMI Play email: ").strip()
    password = os.environ.get("AMI_PLAY_PASSWORD")
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        password = getpass.getpass("AMI Play password: ")
    data = client.login(email, password)
    if args.json:
        emit_json(data)
        return 0
    print(f"Logged in as player {client.session.player_id} ({email}) on {client.env}.")
    try:
        me = client.user()
        if me.get("username"):
            client.session.data["username"] = me["username"]
            client.session.save()
            print(f"Username: {me['username']}")
    except AmiError as e:
        print(f"(profile fetch failed: {e})", file=sys.stderr)
    return 0


def cmd_logout(client: AmiClient, args: argparse.Namespace) -> int:
    if not client.session.logged_in:
        print("Not logged in.")
        return 0
    client.logout()
    print("Logged out; session cleared.")
    return 0


def cmd_reset_password(client: AmiClient, args: argparse.Namespace) -> int:
    data = client.reset_password(args.email)
    if args.json:
        emit_json(data)
    else:
        print(f"Reset email requested for {args.email}. Set a password there, then `ami-play login`.")
    return 0


def cmd_status(client: AmiClient, args: argparse.Namespace) -> int:
    s = client.session
    out: Params = {
        "env": client.env,
        "sessionFile": str(s.path),
        "loggedIn": s.logged_in,
        "email": s.data.get("email"),
        "username": s.data.get("username"),
        "playerId": s.player_id,
        "checkedIn": s.checked_in,
        "geocode": s.geocode,
    }
    if s.logged_in:
        try:
            out["funds"] = client.funds((s.checked_in or {}).get("id"))
        except AmiError as e:
            out["fundsError"] = str(e)
            if e.forces_logout:
                out["loggedIn"] = False
    if args.json:
        emit_json(out)
        return 0
    print(f"Environment : {out['env']}")
    print(f"Session file: {out['sessionFile']}")
    if not s.logged_in:
        print("Login       : not logged in (run `ami-play login`)")
    else:
        who = " / ".join(str(x) for x in (out["username"], out["email"]) if x)
        print(f"Login       : player {s.player_id} {who}".rstrip())
    ci = s.checked_in
    if ci:
        jb = f" (jukebox {ci.get('deviceId')})" if ci.get("deviceId") else " (no jukebox)"
        print(f"Checked in  : {ci.get('name')} [id {ci.get('id')}]{jb}")
    else:
        print("Checked in  : nowhere")
    if s.geocode:
        print(f"Geocode     : {s.geocode['lat']:.5f},{s.geocode['lng']:.5f}")
    if "funds" in out:
        f = out["funds"]
        print(f"Wallet      : {dollars(f.get('walletBalance'))} (bonus {dollars(f.get('playerBonusBalance'))}, promo {dollars(f.get('playerPromoBalance'))})")
    elif "fundsError" in out:
        print(f"Wallet      : {out['fundsError']}")
    return 0


def cmd_me(client: AmiClient, args: argparse.Namespace) -> int:
    data = client.user()
    if args.json:
        emit_json(data)
        return 0
    skip = {"result", "executionTime", "executionTimestamp", "hostName", "authentication"}
    for k in sorted(data):
        if k not in skip:
            print(f"{k}: {data[k]}")
    return 0


def cmd_funds(client: AmiClient, args: argparse.Namespace) -> int:
    ci = client.session.checked_in or {}
    venue_id = args.venue if args.venue is not None else ci.get("id")
    data = client.funds(venue_id)
    if args.json:
        emit_json(data)
        return 0
    jb = {"basePrice": ci.get("basePrice")} if ci.get("basePrice") else None
    rows = [
        ["wallet", dollars(data.get("walletBalance")), credits_for(jb, data.get("walletBalance"))],
        ["bonus", dollars(data.get("playerBonusBalance")), credits_for(jb, data.get("playerBonusBalance"))],
        ["promo", dollars(data.get("playerPromoBalance")), ""],
        ["cash promo", dollars(data.get("playerCashPromoBalance")), ""],
    ]
    print(table(rows, ["balance", "amount", "at this jukebox"]))
    if data.get("playerSessionProgress"):
        print(f"session progress: {dollars(data['playerSessionProgress'])}")
    return 0


def cmd_transactions(client: AmiClient, args: argparse.Namespace) -> int:
    data = client.transactions(args.page, args.per_page)
    if args.json:
        emit_json(data)
        return 0
    txs = data.get("transactions") or data.get("items") or []
    if not txs:
        print("No transactions.")
        return 0
    rows = []
    for t in txs:
        rows.append([t.get("transactionId") or t.get("id"), t.get("date") or t.get("timestamp") or t.get("purchaseDate"), t.get("locationName") or t.get("location"), t.get("title") or t.get("songTitle") or t.get("description"), t.get("subtitle") or t.get("artistName"), dollars(t.get("amount") if t.get("amount") is not None else t.get("price")), t.get("status")])
    print(table(rows, ["id", "when", "venue", "item", "by", "amount", "status"]))
    return 0


def cmd_venues(client: AmiClient, args: argparse.Namespace) -> int:
    session = client.session
    sub = args.venues_cmd
    if sub == "search":
        geo = parse_geocode(args.at, session)
        venues = client.venues_search(args.query, geo, args.page, args.per_page, [DEVICE_TYPE_MUSIC] if args.jukebox_only else None)
    elif sub == "near":
        geo = parse_geocode(args.coords, session)
        venues = client.venues_search(None, geo, args.page, args.per_page, [DEVICE_TYPE_MUSIC] if args.jukebox_only else None)
    elif sub == "recent":
        venues = client.venues_recent(parse_geocode(args.at, session))
    elif sub == "favorites":
        venues = client.venues_favorites(parse_geocode(args.at, session))
    elif sub == "favorite":
        data = client.venue_set_favorite(args.id, not args.remove)
        if args.json:
            emit_json(data)
        else:
            print(f"Venue {args.id} {'removed from' if args.remove else 'added to'} favorites.")
        return 0
    else:
        raise AmiError(None, f"unknown venues subcommand {sub!r}")
    if args.json:
        emit_json(venues)
        return 0
    if not venues:
        print("No venues.")
        return 0
    print(table([venue_row(v) for v in venues], VENUE_HEADERS))
    print("(* favorite, ! not interactable right now)")
    return 0


def describe_jukebox(jb: Params, client: AmiClient) -> list[str]:
    lines = []
    base = jb.get("basePrice") or 0
    lines.append(f"  jukebox {jb.get('deviceId')} '{jb.get('deviceName', '')}'  mode {jb.get('mode')}  interact: {jb.get('canInteract')} ({jb.get('canInteractReason', '')})")
    if jb.get("isFreeplay"):
        lines.append("  free play")
    else:
        song_p = client.price_in_pennies(jb, local=False)
        local_p = client.price_in_pennies(jb, local=True)
        pri_p = client.price_in_pennies(jb, local=False, priority=True)
        lines.append(f"  credit = {dollars(base)}   song: {credits_for(jb, song_p)} (local {credits_for(jb, local_p)})   priority: {credits_for(jb, pri_p)}   video: {jb.get('canPlayVideo')}")
        if jb.get("dynamicPricingOn"):
            lines.append(f"  dynamic pricing ON: level {jb.get('dpLevelUsed')}, +{jb.get('dpAdditionalCredits')} credit(s), est. queue position {jb.get('dpEstPosInQueue')}")
        tiers = jb.get("pricing") or []
        if tiers:
            lines.append("  buy-in tiers: " + ", ".join(f"{t.get('credits')} for {dollars(t.get('price'))}" for t in tiers))
    if jb.get("queueDepth") is not None:
        lines.append(f"  queue depth: {jb.get('queueDepth')}")
    if jb.get("nowPlaying") and not jb.get("nowPlayingSongInfo"):
        lines.append(f"  now playing: song {jb.get('nowPlaying')} (see `ami-play queue`)")
    return lines


def cmd_venue(client: AmiClient, args: argparse.Namespace) -> int:
    venue = client.venue(args.id)
    if args.json:
        emit_json(venue)
        return 0
    geo = venue.get("geocode") or {}
    print(f"{venue.get('name')} [id {venue.get('id')}]  {venue.get('address1', '')}, {venue.get('city', '')}, {venue.get('state', '')} {venue.get('zipcode', '')}")
    print(f"  mobile enabled: {venue.get('mobileEnabled')}   currency: {venue.get('currency')}   geocode: {geo.get('lat')},{geo.get('lng')}")
    for d in venue.get("devices") or []:
        if d.get("deviceType") == DEVICE_TYPE_MUSIC:
            print("\n".join(describe_jukebox(d, client)))
        else:
            print(f"  {DEVICE_TYPE_NAMES.get(d.get('deviceType'), d.get('deviceType'))} {d.get('deviceId')} '{d.get('deviceName', '')}'  interact: {d.get('canInteract')}")
    if not venue.get("devices"):
        print("  (no devices listed)")
    return 0


def cmd_checkin(client: AmiClient, args: argparse.Namespace) -> int:
    venue = client.venue(args.id)
    geo = parse_geocode(args.at, client.session, venue)
    data = client.checkin(args.id, geo)
    jb = remember_venue(client.session, venue)
    if args.json:
        emit_json(data)
        return 0
    print(f"Checked in at {venue.get('name')} [id {venue['id']}]" + (f", jukebox {jb['deviceId']}." if jb else ", no jukebox here."))
    return 0


def cmd_checkout(client: AmiClient, args: argparse.Namespace) -> int:
    data = client.checkout(parse_geocode(args.at, client.session))
    client.session.checked_in = None
    client.session.save()
    if args.json:
        emit_json(data)
    else:
        print("Checked out.")
    return 0


def cmd_queue(client: AmiClient, args: argparse.Namespace) -> int:
    venue, jb = resolve_venue(client, args)
    if not jb:
        raise AmiError(None, f"{venue.get('name')} has no jukebox")
    data = client.play_queue(jb["deviceId"], jb.get("deviceType") or DEVICE_TYPE_MUSIC)
    if args.json:
        emit_json(data)
        return 0
    now = (data.get("nowPlaying") or {}).get("songInfo")
    print(f"{venue.get('name')} (jukebox {jb['deviceId']})")
    if now:
        print(f"Now playing: {now.get('songTitle')} - {now.get('artistName')} [{duration(now.get('durationSec'))}]")
    else:
        print("Now playing: (nothing / not reported)")
    queue = data.get("playQueue") or []
    if not queue:
        print("Queue: empty")
        return 0
    rows = [[q.get("order"), *song_row(q.get("songInfo") or {})] for q in queue]
    print(table(rows, ["#", *SONG_HEADERS]))
    return 0


def cmd_search(client: AmiClient, args: argparse.Namespace) -> int:
    device_id = None
    if args.venue is not None or client.session.checked_in:
        try:
            _, jb = resolve_venue(client, args)
            device_id = jb["deviceId"] if jb else None
        except AmiError:
            device_id = None
    data = client.search(args.query, device_id, args.page, args.per_page, args.sort, args.order)
    if args.json:
        emit_json(data)
        return 0
    kinds = ("songs", "artists", "albums") if args.type == "all" else (args.type,)
    shown = False
    if "songs" in kinds and data.get("songs"):
        shown = True
        print(f"Songs ({data.get('songHits', len(data['songs']))} hits, page {args.page}):")
        print(table([song_row(s) for s in data["songs"]], SONG_HEADERS))
    if "artists" in kinds and data.get("artists"):
        shown = True
        print(f"\nArtists ({data.get('artistHits', len(data['artists']))} hits):")
        print(table([[a.get("artistId"), a.get("artistName"), a.get("songCount"), a.get("albumCount")] for a in data["artists"]], ["artistId", "artist", "songs", "albums"]))
    if "albums" in kinds and data.get("albums"):
        shown = True
        print(f"\nAlbums ({data.get('albumHits', len(data['albums']))} hits):")
        print(table([[a.get("albumId"), a.get("albumName"), a.get("artistName"), a.get("releaseYear"), a.get("songCount")] for a in data["albums"]], ["albumId", "album", "artist", "year", "songs"]))
    if not shown:
        print("No results.")
    if device_id is None:
        print("(searched network-wide: no venue selected, so availability on a specific jukebox is not checked)")
    return 0


def _device_for(client: AmiClient, args: argparse.Namespace) -> str | int | None:
    if args.venue is None and not client.session.checked_in:
        return None
    _, jb = resolve_venue(client, args)
    return jb["deviceId"] if jb else None


def cmd_song(client: AmiClient, args: argparse.Namespace) -> int:
    song = client.song(args.id, _device_for(client, args))
    if args.json:
        emit_json(song)
        return 0
    if not song:
        print("Song not found.")
        return 1
    print(table([song_row(song)], SONG_HEADERS))
    return 0


def cmd_album(client: AmiClient, args: argparse.Namespace) -> int:
    dev = _device_for(client, args)
    data = client.album(args.id, dev, args.page, args.per_page, args.sort, args.order)
    if args.json:
        emit_json(data)
        return 0
    info = client.album_info(args.id, dev) or {}
    if info:
        print(f"{info.get('albumName')} - {info.get('artistName')} ({info.get('releaseYear', '')}, {info.get('songCount')} songs) [albumId {info.get('albumId')}]")
    songs = data.get("songs") or []
    print(table([song_row(s) for s in songs], SONG_HEADERS) if songs else "No songs.")
    return 0


def cmd_artist(client: AmiClient, args: argparse.Namespace) -> int:
    dev = _device_for(client, args)
    allowed = ("title", "year") if args.media == "albums" else ("title", "popularity")
    if args.sort and args.sort not in allowed:
        raise AmiError(None, f"--sort for {args.media} must be one of: {', '.join(allowed)}")
    data = client.artist(args.id, dev, args.media, args.page, args.per_page, args.sort, args.order)
    if args.json:
        emit_json(data)
        return 0
    artist = data.get("artist") or {}
    if artist:
        print(f"{artist.get('artistName')} [artistId {artist.get('artistId')}] songs {artist.get('songCount')} albums {artist.get('albumCount')}")
    if args.media == "albums":
        albums = data.get("albums") or []
        print(table([[a.get("albumId"), a.get("albumName"), a.get("releaseYear"), a.get("songCount")] for a in albums], ["albumId", "album", "year", "songs"]) if albums else "No albums.")
    else:
        songs = data.get("songs") or []
        print(table([song_row(s) for s in songs], SONG_HEADERS) if songs else "No songs.")
    return 0


def cmd_lists(client: AmiClient, args: argparse.Namespace) -> int:
    venue, jb = resolve_venue(client, args)
    lists = client.lists(venue["id"], jb["deviceId"] if jb else None)
    if args.json:
        emit_json(lists)
        return 0
    if not lists:
        print("No lists.")
        return 0
    print(table([[m.get("identifier"), m.get("displayTitle"), m.get("listType"), m.get("displayType"), m.get("selectionCode")] for m in lists], ["identifier", "title", "type", "display", "selection"]))
    return 0


def render_items(items: list[Params]) -> str:
    """Table for a homogeneous list of songs, artists, albums or featured playlists."""
    if not items:
        return "(empty)"
    first = items[0]
    if "songId" in first:
        return table([song_row(s) for s in items], SONG_HEADERS)
    if "artistId" in first and "artistName" in first and "albumName" not in first:
        return table([[a.get("artistId"), a.get("artistName"), a.get("songCount"), a.get("albumCount")] for a in items], ["artistId", "artist", "songs", "albums"])
    if "albumId" in first:
        return table([[a.get("albumId"), a.get("albumName"), a.get("artistName"), a.get("releaseYear"), a.get("songCount")] for a in items], ["albumId", "album", "artist", "year", "songs"])
    if "itemsCount" in first or "playlistId" in first:
        return table([[pl.get("id") or pl.get("playlistId"), pl.get("title"), pl.get("itemsCount") or pl.get("songCount"), pl.get("type", "")] for pl in items], ["id", "title", "items", "type"])
    return json.dumps(items, indent=2, sort_keys=True)


def cmd_list(client: AmiClient, args: argparse.Namespace) -> int:
    venue, jb = resolve_venue(client, args)
    data = client.list_data(venue["id"], jb["deviceId"] if jb else None, args.identifier)
    if args.json:
        emit_json(data)
        return 0
    items = data.get("listData")
    if items is None:
        for key in ("songs", "artists", "albums", "playlists", "videos"):
            if data.get(key):
                items = data[key]
                break
    if items is None:
        skip = {"result", "executionTime", "executionTimestamp", "hostName"}
        emit_json({k: v for k, v in data.items() if k not in skip})
        return 0
    print(render_items(list(items)))
    if items and ("itemsCount" in items[0] or "playlistId" in items[0]):
        print("(open one with `ami-play featured <id>`)")
    return 0


def cmd_featured(client: AmiClient, args: argparse.Namespace) -> int:
    venue, jb = resolve_venue(client, args)
    data = client.featured_playlist(args.id, venue["id"], jb["deviceId"] if jb else None)
    if args.json:
        emit_json(data)
        return 0
    pl = data.get("playlist") or data
    if pl.get("title"):
        print(f"{pl.get('title')} [id {pl.get('id') or args.id}]  {pl.get('description', '')}".rstrip())
    items = pl.get("songs") or pl.get("items") or data.get("songs") or data.get("listData") or []
    print(render_items(list(items)))
    return 0


def cmd_play(client: AmiClient, args: argparse.Namespace) -> int:
    venue, jb = resolve_venue(client, args, fresh=True)
    if not jb:
        raise AmiError(None, f"{venue.get('name')} has no jukebox to play on")
    if not jb.get("canInteract", True) and not args.force:
        raise AmiError(None, f"jukebox reports it cannot take plays right now ({jb.get('canInteractReason')}); --force to try anyway")
    song = client.song(args.song_id, jb["deviceId"])
    if not song:
        raise AmiError(None, f"song {args.song_id} not found for this jukebox")
    amount = args.amount if args.amount is not None else client.price_in_pennies(jb, local=bool(song.get("local")), priority=args.priority, video=args.video)
    funds = client.funds(venue["id"])
    wallet = int(funds.get("walletBalance") or 0) + int(funds.get("playerBonusBalance") or 0)
    label = f"{song.get('songTitle')} - {song.get('artistName')}"
    cost = f"{amount} pennies" if not jb.get("basePrice") else f"{credits_for(jb, amount)} ({dollars(amount)})"
    print(f"Play: {label}\nAt  : {venue.get('name')} [id {venue['id']}], jukebox {jb['deviceId']}{' PRIORITY' if args.priority else ''}\nCost: {cost}   wallet+bonus: {dollars(wallet)}")
    threshold = jb.get("longSongDurationThreshold")
    if jb.get("isLongSongUpchargeActive") and threshold and int(song.get("durationSec") or 0) > int(threshold):
        print(f"Note: this song runs past {int(threshold) // 60} min, so the jukebox adds {jb.get('longSongUpchargeCredits')} credit(s) on top.")
    if jb.get("dynamicPricingOn"):
        print(f"Note: dynamic pricing is on (+{jb.get('dpAdditionalCredits')} credit(s) at level {jb.get('dpLevelUsed')}); the server may charge more than the base cost.")
    if amount > wallet and not args.force:
        raise AmiError(None, "not enough funds; add credits in the app or pass --force to let the server decide")
    if not args.yes:
        if not sys.stdin.isatty():
            raise AmiError(None, "refusing to spend credits without --yes in a non-interactive session")
        answer = input("Spend it? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return 0
    data = client.purchase(venue["id"], jb, song, priority=args.priority, video=args.video, selection=args.selection, amount=amount)
    if args.json:
        emit_json(data)
        return 0
    print(f"Queued. transaction {data.get('transactionId')}  status {data.get('status')}  charged {dollars(data.get('amountUsed'))} (bonus used {dollars(data.get('bonusUsed'))})  wallet now {dollars(data.get('walletBalance'))}")
    return 0


def cmd_favorites(client: AmiClient, args: argparse.Namespace) -> int:
    songs = client.favorites(_device_for(client, args), args.page, args.per_page)
    if args.json:
        emit_json(songs)
        return 0
    print(table([song_row(s) for s in songs], SONG_HEADERS) if songs else "No favorites.")
    return 0


def cmd_favorite(client: AmiClient, args: argparse.Namespace) -> int:
    data = client.set_favorite(args.song_id, not args.remove)
    if args.json:
        emit_json(data)
    else:
        print(f"Song {args.song_id} {'removed from' if args.remove else 'added to'} favorites.")
    return 0


def cmd_playlists(client: AmiClient, args: argparse.Namespace) -> int:
    lists = client.playlists()
    if args.json:
        emit_json(lists)
        return 0
    print(table([[p.get("playlistId") or p.get("id"), p.get("title"), p.get("songCount")] for p in lists], ["playlistId", "title", "songs"]) if lists else "No playlists.")
    return 0


def cmd_playlist(client: AmiClient, args: argparse.Namespace) -> int:
    sub = args.playlist_cmd
    if sub == "show":
        pl = client.playlist(args.id, _device_for(client, args), args.page, args.per_page)
        if args.json:
            emit_json(pl)
            return 0
        print(f"{pl.get('title')} [playlistId {pl.get('playlistId') or pl.get('id')}] {pl.get('songCount')} songs")
        songs = pl.get("songs") or []
        print(table([song_row(s) for s in songs], SONG_HEADERS) if songs else "(empty)")
        return 0
    if sub == "create":
        pl = client.playlist_create(args.title)
        emit_json(pl) if args.json else print(f"Created playlist {pl.get('playlistId') or pl.get('id')}: {pl.get('title')}")
        return 0
    if sub == "add":
        data = client.playlist_add(args.id, args.song_id, _device_for(client, args))
        emit_json(data) if args.json else print(f"Added song {args.song_id} to playlist {args.id}.")
        return 0
    if sub == "rename":
        data = client.playlist_rename(args.id, args.title)
        emit_json(data) if args.json else print(f"Renamed playlist {args.id}.")
        return 0
    if sub == "set-songs":
        data = client.playlist_set_songs(args.id, args.song_ids)
        emit_json(data) if args.json else print(f"Playlist {args.id} now has {len(args.song_ids)} song(s).")
        return 0
    if sub == "delete":
        if not args.yes:
            raise AmiError(None, "pass --yes to delete a playlist")
        data = client.playlist_delete(args.id)
        emit_json(data) if args.json else print(f"Deleted playlist {args.id}.")
        return 0
    raise AmiError(None, f"unknown playlist subcommand {sub!r}")


def cmd_raw(client: AmiClient, args: argparse.Namespace) -> int:
    params: Params = json.loads(args.data) if args.data else {}
    if not args.no_auth and client.session.logged_in:
        params = {**client._auth(required=False), **params}  # noqa: SLF001  (raw mode deliberately reuses the client's auth builder)
    data = client._call(args.method, args.path, params, ok=lambda code: True)  # noqa: SLF001  (raw mode shows every result code)
    emit_json(data)
    return 0 if data.get("result", 0) == 0 else 1


# -- argparse ----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ami-play", description="Unofficial CLI for the AMI Play jukebox service.")
    p.add_argument("--json", action="store_true", help="print the raw JSON response instead of a table")
    p.add_argument("--env", choices=sorted(ENVIRONMENTS), help="server environment (default: the session's, normally prod)")
    p.add_argument("--session", help="path to the session file (default: secrets/session.json or $AMI_PLAY_SESSION)")
    sub = p.add_subparsers(dest="cmd", required=True)
    # A copy of the global flags on every subparser, so `ami-play venue 1 --json` works too.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--env", choices=sorted(ENVIRONMENTS), default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--session", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    _add_parser = sub.add_parser

    def add_parser(name: str, **kw: Any) -> argparse.ArgumentParser:
        return _add_parser(name, parents=[common], **kw)

    def venue_opt(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--venue", type=int, help="venue (location) id; default: the checked-in venue")

    def paging(sp: argparse.ArgumentParser, per_page: int = 20) -> None:
        sp.add_argument("--page", type=int, default=1)
        sp.add_argument("--per-page", type=int, default=per_page)

    sp = add_parser("login", help="log in with email + password (prompted; or $AMI_PLAY_PASSWORD / --password-stdin)")
    sp.add_argument("email", nargs="?")
    sp.add_argument("--password-stdin", action="store_true")
    sp.set_defaults(fn=cmd_login)
    add_parser("logout", help="log out and clear the session").set_defaults(fn=cmd_logout)
    sp = add_parser("reset-password", help="email a password reset link (turns an SSO-only account into one that can log in here)")
    sp.add_argument("email")
    sp.set_defaults(fn=cmd_reset_password)
    add_parser("status", help="session, checked-in venue, wallet").set_defaults(fn=cmd_status)
    add_parser("me", help="account profile").set_defaults(fn=cmd_me)
    sp = add_parser("funds", help="wallet, bonus and promo balances")
    venue_opt(sp)
    sp.set_defaults(fn=cmd_funds)
    sp = add_parser("transactions", help="purchase history")
    paging(sp)
    sp.set_defaults(fn=cmd_transactions)

    sp = add_parser("venues", help="find venues")
    vs = sp.add_subparsers(dest="venues_cmd", required=True)
    _vs_add = vs.add_parser
    vs.add_parser = lambda name, **kw: _vs_add(name, parents=[common], **kw)  # type: ignore[method-assign]
    v = vs.add_parser("search", help="search venues by name (distance uses --at or the remembered geocode)")
    v.add_argument("query")
    v.add_argument("--at", help="LAT,LNG to measure distance from (remembered for later)")
    v.add_argument("--jukebox-only", action="store_true")
    paging(v)
    v = vs.add_parser("near", help="venues around LAT,LNG")
    v.add_argument("coords", help="LAT,LNG")
    v.add_argument("--jukebox-only", action="store_true")
    paging(v)
    v = vs.add_parser("recent", help="venues you checked in at recently")
    v.add_argument("--at")
    v = vs.add_parser("favorites", help="your favorite venues")
    v.add_argument("--at")
    v = vs.add_parser("favorite", help="favorite / unfavorite a venue")
    v.add_argument("id", type=int)
    v.add_argument("--remove", action="store_true")
    sp.set_defaults(fn=cmd_venues)

    sp = add_parser("venue", help="venue details incl. jukebox pricing and state")
    sp.add_argument("id", type=int)
    sp.set_defaults(fn=cmd_venue)
    sp = add_parser("checkin", help="check in at a venue (remembered as the default venue)")
    sp.add_argument("id", type=int)
    sp.add_argument("--at", help="LAT,LNG, or 'venue' to report the venue's own coordinates")
    sp.set_defaults(fn=cmd_checkin)
    sp = add_parser("checkout", help="check out of the current venue")
    sp.add_argument("--at")
    sp.set_defaults(fn=cmd_checkout)
    sp = add_parser("queue", help="now playing + play queue on the jukebox")
    venue_opt(sp)
    sp.set_defaults(fn=cmd_queue)

    sp = add_parser("search", help="search songs, artists and albums")
    sp.add_argument("query")
    venue_opt(sp)
    sp.add_argument("--type", choices=["all", "songs", "artists", "albums"], default="all")
    sp.add_argument("--sort", choices=["title", "popularity"])
    sp.add_argument("--order", choices=["asc", "desc"])
    paging(sp)
    sp.set_defaults(fn=cmd_search)
    sp = add_parser("song", help="one song by id")
    sp.add_argument("id", type=int)
    venue_opt(sp)
    sp.set_defaults(fn=cmd_song)
    sp = add_parser("album", help="an album's songs")
    sp.add_argument("id", type=int)
    venue_opt(sp)
    sp.add_argument("--sort", choices=["track", "title", "popularity"], default="track")
    sp.add_argument("--order", choices=["asc", "desc"])
    paging(sp, 50)
    sp.set_defaults(fn=cmd_album)
    sp = add_parser("artist", help="an artist's songs or albums")
    sp.add_argument("id", type=int)
    venue_opt(sp)
    sp.add_argument("--media", choices=["songs", "albums"], default="songs")
    sp.add_argument("--sort", choices=["title", "popularity", "year"], help="songs: title|popularity (default popularity); albums: title|year (default year)")
    sp.add_argument("--order", choices=["asc", "desc"])
    paging(sp)
    sp.set_defaults(fn=cmd_artist)
    sp = add_parser("lists", help="the venue's featured lists (top 40, staff picks, featured playlists)")
    venue_opt(sp)
    sp.set_defaults(fn=cmd_lists)
    sp = add_parser("list", help="items in one featured list")
    sp.add_argument("identifier")
    venue_opt(sp)
    sp.set_defaults(fn=cmd_list)

    sp = add_parser("featured", help="songs in one featured playlist (ids come from `list jukebox_featured_playlists`)")
    sp.add_argument("id", type=int)
    venue_opt(sp)
    sp.set_defaults(fn=cmd_featured)

    sp = add_parser("play", help="queue a song on the jukebox (SPENDS CREDITS)")
    sp.add_argument("song_id", type=int)
    venue_opt(sp)
    sp.add_argument("--priority", action="store_true", help="priority play (jumps the queue, costs more)")
    sp.add_argument("--video", action="store_true", help="play the music video instead of the song")
    sp.add_argument("--amount", type=int, help="override the computed price in pennies")
    sp.add_argument("--selection", choices=sorted(SELECTION_CODES), default="search_song", help="where the pick came from (analytics field the app always sends)")
    sp.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    sp.add_argument("--force", action="store_true", help="ignore the local funds and can-interact checks")
    sp.set_defaults(fn=cmd_play)

    sp = add_parser("favorites", help="your favorite songs")
    venue_opt(sp)
    paging(sp, 50)
    sp.set_defaults(fn=cmd_favorites)
    sp = add_parser("favorite", help="favorite / unfavorite a song")
    sp.add_argument("song_id", type=int)
    sp.add_argument("--remove", action="store_true")
    sp.set_defaults(fn=cmd_favorite)
    add_parser("playlists", help="your playlists").set_defaults(fn=cmd_playlists)
    sp = add_parser("playlist", help="manage one playlist")
    ps = sp.add_subparsers(dest="playlist_cmd", required=True)
    _ps_add = ps.add_parser
    ps.add_parser = lambda name, **kw: _ps_add(name, parents=[common], **kw)  # type: ignore[method-assign]
    q = ps.add_parser("show")
    q.add_argument("id", type=int)
    venue_opt(q)
    paging(q, 100)
    q = ps.add_parser("create")
    q.add_argument("title")
    q = ps.add_parser("add")
    q.add_argument("id", type=int)
    q.add_argument("song_id", type=int)
    venue_opt(q)
    q = ps.add_parser("rename")
    q.add_argument("id", type=int)
    q.add_argument("title")
    q = ps.add_parser("set-songs")
    q.add_argument("id", type=int)
    q.add_argument("song_ids", type=int, nargs="*")
    q = ps.add_parser("delete")
    q.add_argument("id", type=int)
    q.add_argument("--yes", "-y", action="store_true")
    sp.set_defaults(fn=cmd_playlist)

    sp = add_parser("raw", help="call any endpoint: raw POST location/v3/search --data '{\"name\":\"zoo\"}'")
    sp.add_argument("method", choices=["GET", "POST", "get", "post"])
    sp.add_argument("path")
    sp.add_argument("--data", help="JSON object of parameters")
    sp.add_argument("--no-auth", action="store_true", help="do not add playerId/authentication")
    sp.set_defaults(fn=cmd_raw)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session = Session(args.session)
    try:
        client = AmiClient(session, env=args.env)
        return int(args.fn(client, args))
    except AmiError as e:
        print(f"ami-play: {e}", file=sys.stderr)
        if e.forces_logout:
            print("ami-play: the server rejected the session; run `ami-play login` again", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ValueError as e:
        print(f"ami-play: {e}", file=sys.stderr)
        return 2
