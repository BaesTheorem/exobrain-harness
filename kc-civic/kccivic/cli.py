"""kc-civic: sync Kansas City public meetings to Google Calendar and prep remarks.

Sources: the KCMO Legistar Web API (council, committees, commissions) and the EDC of
Kansas City events feed (TIF, PIEA, LCRA boards). Bodies are chosen in config.json.

  kc-civic list [--edc]            meetings the next sync would write
  kc-civic sync [--no-edc] [--force-edc] [--no-prep] [--dry-run]
  kc-civic prep KEY [--force]      build the packet and prep note for one meeting
  kc-civic auth-calendar [--code URL_OR_CODE]
  kc-civic status

INVARIANTS:
- One notification per sync pass at most (a digest), with --discord.
- The calendar body is rebuilt from the Meeting and the prep state on every write,
  so the description never accumulates stale lines.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from . import gcal, holds, legistar, prep
from .model import TZ, Meeting

HERE = Path(__file__).resolve().parent.parent
HARNESS = HERE.parent
DATA = HERE / "data"
STATE_PATH = DATA / "state.json"
NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"
CITY_HALL = "City Hall, 414 E 12th St, Kansas City, MO 64106"


def load_config() -> dict:
    return json.loads((HERE / "config.json").read_text())


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"synced": {}, "prepped": {}, "last_edc": 0, "edc_cache": [], "notices": {}}


def save_state(st: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, default=str))
    tmp.replace(STATE_PATH)


def vault_dir(cfg: dict) -> Path:
    return Path(cfg["vault_dir"]).expanduser()


def note_path(cfg: dict, m: Meeting) -> Path:
    return vault_dir(cfg) / "Meeting Prep" / f"{m.start:%Y-%m-%d} {m.short}.md"


def obsidian_link(p: Path) -> str:
    rel = p.relative_to(Path.home() / "Exobrain").with_suffix("")
    return "obsidian://open?vault=Exobrain&file=" + urllib.parse.quote(str(rel))


def _ser(m: Meeting) -> dict:
    d = dict(m.__dict__)
    d["start"], d["end"] = m.start.isoformat(), m.end.isoformat()
    return d


def _de(d: dict) -> Meeting:
    d = dict(d)
    d["start"], d["end"] = datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"])
    return Meeting(**d)


def event_body(m: Meeting, prepped: dict | None) -> dict:
    loc = m.location
    if loc and "12th" not in loc and any(w in loc.lower() for w in ("council chamber", "city hall", "floor")):
        loc = f"{loc}, {CITY_HALL}"
    lines = [f"{m.body} (tier {m.tier})", ""]
    if m.source == "hold":
        lines += ["EXPECTED, NOT YET PUBLISHED. This is a hold kc-civic put here because this body meets "
                  f"{m.extra.get('pattern', 'on a fixed schedule')}.",
                  "When the city publishes the meeting, this entry changes to the official time, place, "
                  "agenda and join link. If the city never publishes it, this hold is deleted a few hours before "
                  "the start time.", ""]
    elif prepped and prepped.get("note"):
        s = prepped.get("summary") or {}
        lines += [f"Prep note: {obsidian_link(Path(prepped['note']))}",
                  f"Verdict: {s.get('verdict', '?')}. Public comment: {s.get('public_comment', '?')}.",
                  s.get("headline", ""), ""]
    elif m.source == "legistar" and not m.agenda_url:
        lines += ["Agenda not posted yet. A prep note follows when it is.", ""]
    if m.join_link:
        lines.append(f"Join remotely: {m.join_link}")
    if m.agenda_url:
        lines.append(f"Agenda: {m.agenda_url}")
    if m.url:
        lines.append(f"Meeting page: {m.url}")
    if m.extra.get("comment") and m.extra["comment"] not in m.join_link:
        lines += ["", m.extra["comment"]]
    if not m.extra.get("time_known", True):
        lines += ["", "NOTE: the source gives no start time; 9:00 AM is a placeholder."]
    src = {"legistar": "Legistar", "edc": "edckc.com", "hold": "its 2026 meeting cadence"}[m.source]
    lines += ["", f"Synced by kc-civic from {src}."]
    return {
        "summary": m.title(),
        "description": "\n".join(lines),
        "location": loc,
        "start": {"dateTime": m.start.isoformat(), "timeZone": "America/Chicago"},
        "end": {"dateTime": m.end.isoformat(), "timeZone": "America/Chicago"},
        "colorId": str(load_config().get("color_id", "7")),
        **({"source": {"title": m.short, "url": m.url}} if m.url.startswith("http") else {}),
    }


def fetch_edc(cfg: dict, st: dict, force: bool, pg=None) -> list[Meeting]:
    """EDC meetings: live when the gate allows (or pg is open), else the cached copy."""
    from . import edc, walled

    age_h = (datetime.now().timestamp() - float(st.get("last_edc", 0))) / 3600
    if pg is None and not force and age_h < cfg["edc_min_hours_between"]:
        return [_de(d) for d in st.get("edc_cache", [])]
    text = walled.page_fetch_text(pg, cfg["edc"]["ical"]) if pg is not None else None
    if text is None:
        with walled.browser_page(cfg["edc"]["home"]) as page:
            text = walled.page_fetch_text(page, cfg["edc"]["ical"])
    ms = edc.to_meetings(edc.parse_ics(text), cfg["edc"]["bodies"], cfg["sync_days"])
    st["last_edc"] = datetime.now().timestamp()
    st["edc_cache"] = [_ser(m) for m in ms]
    return ms


def notify(msg: str, link: str, context: str) -> None:
    try:
        subprocess.run([str(NOTIFY), msg, "KC Civic", "Purr", link, "--group", "watchers",
                        "--discord", "--context", context], timeout=60, check=False)
    except OSError as e:
        print(f"notify failed: {e}", file=sys.stderr)


def write_calendar(cfg: dict, st: dict, meetings: list[Meeting], dry: bool) -> tuple[list[str], str | None]:
    """Returns (labels of newly published meetings, error). A published meeting takes
    over the hold for its body and date, so the calendar keeps one entry per slot."""
    cal = gcal.calendar_id(cfg.get("calendar_id", "primary"))
    created = []
    for m in meetings:
        p = st["prepped"].get(m.key)
        h = m.content_hash() + (p.get("note", "") + str(p.get("summary")) if p else "")
        if st["synced"].get(m.key, {}).get("hash") == h:
            continue
        if dry:
            print(f"would write: {m.start:%a %m/%d %I:%M %p} {m.title()}")
            continue
        hk = holds.hold_key(m.short, m.start.date())
        adopt = None
        if m.source != "hold" and m.key not in st["synced"]:
            adopt = st["synced"].get(hk, {}).get("event_id")
        try:
            action, ev = gcal.upsert(cal, m.key, event_body(m, p), adopt=adopt)
        except gcal.NotAuthorized as e:
            return created, str(e)
        st["synced"][m.key] = {"hash": h, "event_id": ev.get("id"), "link": ev.get("htmlLink"),
                               "start": m.start.isoformat(), "meeting": _ser(m)}
        if action == "adopted":
            st["synced"].pop(hk, None)
        if m.source != "hold" and action in ("created", "adopted"):
            created.append(f"{m.start:%a %-m/%-d} {m.short}")
        print(f"{action}: {m.start:%Y-%m-%d %H:%M} {m.title()}")
    return created, None


def mark_vanished(cfg: dict, st: dict, live_keys: set[str], dry: bool) -> None:
    """A synced future Legistar meeting that left the feed: re-check it by id."""
    now = datetime.now(TZ)
    for key, rec in list(st["synced"].items()):
        if not key.startswith("legistar-") or key in live_keys or "meeting" not in rec:
            continue
        m = _de(rec["meeting"])
        if m.start < now or m.cancelled:
            continue
        ev = legistar.event(int(m.source_id))
        if ev and (ev.get("EventDate") or "")[:10] == m.start.date().isoformat():
            continue  # still there, just outside this query's window
        m.cancelled = True
        if not dry:
            try:
                gcal.upsert(gcal.calendar_id(cfg.get("calendar_id", "primary")), key, event_body(m, None))
                rec["meeting"] = _ser(m)
            except gcal.NotAuthorized:
                return


def drop_stale_holds(cfg: dict, st: dict, live: set[str], dry: bool) -> list[str]:
    """Delete holds whose slot is near or past and that no published meeting took over."""
    cal = gcal.calendar_id(cfg.get("calendar_id", "primary"))
    now = datetime.now(TZ)
    dropped = []
    for key, rec in list(st["synced"].items()):
        if not key.startswith("hold-") or key in live:
            continue
        start = datetime.fromisoformat(rec["start"])
        if start - now > holds.HOLD_CUTOFF:
            continue  # left the generator for another reason (config edit); leave it
        if dry:
            print(f"would drop hold: {key}")
            continue
        if rec.get("event_id"):
            gcal.delete(cal, rec["event_id"])
        st["synced"].pop(key)
        dropped.append(key)
        print(f"dropped unconfirmed hold: {key}")
    return dropped


def prep_candidates(cfg: dict, st: dict, meetings: list[Meeting]) -> list[Meeting]:
    now = datetime.now(TZ)
    out = []
    for m in sorted(meetings, key=lambda x: x.start):
        if m.source == "hold" or m.cancelled or not (now + timedelta(hours=1) < m.start < now + timedelta(days=cfg["prep_lead_days"])):
            continue
        if m.source == "legistar" and not m.agenda_url and not m.extra.get("pages"):
            continue
        done = st["prepped"].get(m.key)
        if done and (done.get("fingerprint") == m.agenda_fingerprint or m.start < now + timedelta(hours=12)):
            continue
        out.append(m)
    return out


def do_prep(cfg: dict, st: dict, m: Meeting, pg=None) -> dict | None:
    packet = DATA / "packets" / f"{m.start:%Y-%m-%d}-{m.key}"
    packet.mkdir(parents=True, exist_ok=True)
    extra = prep.build_legistar_packet(m, packet) if m.source == "legistar" else {}
    pages = m.extra.get("pages") or []
    if pages:
        from . import walled
        if pg is None:
            with walled.browser_page(pages[0]) as page:
                extra.update(prep.snapshot_pages(m, packet, page))
        else:
            extra.update(prep.snapshot_pages(m, packet, pg))
    prep.write_meeting_json(m, packet, extra)
    note = note_path(cfg, m)
    note.parent.mkdir(parents=True, exist_ok=True)
    summary = prep.run_claude(m, packet, note)
    if summary is None:
        print(f"prep FAILED for {m.key}; see {packet / 'claude.log'}", file=sys.stderr)
        return None
    rec = {"fingerprint": m.agenda_fingerprint, "note": str(note), "summary": summary,
           "at": datetime.now(TZ).isoformat()}
    st["prepped"][m.key] = rec
    return rec


def gather(cfg: dict, st: dict, args, pg=None) -> list[Meeting]:
    ms = legistar.meetings(cfg["legistar"], cfg["sync_days"])
    if not getattr(args, "no_edc", False):
        try:
            ms += fetch_edc(cfg, st, getattr(args, "force_edc", False), pg)
        except Exception as e:  # noqa: BLE001 -- a walled EDC site must not stop the Legistar sync
            print(f"EDC fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
            ms += [_de(d) for d in st.get("edc_cache", [])]
    if not getattr(args, "no_holds", False):
        taken = {(m.short, m.start.date()) for m in ms}
        ms += [h for h in holds.generate(cfg.get("holds", []), cfg["sync_days"], set(cfg.get("hold_skip_dates", [])))
               if (h.short, h.start.date()) not in taken]
    return ms


def cmd_list(cfg: dict, args) -> int:
    st = load_state()
    for m in sorted(gather(cfg, st, args), key=lambda x: x.start):
        flag = "hold" if m.source == "hold" else "agenda" if (m.agenda_url or m.extra.get("pages")) else "no agenda"
        print(f"{m.start:%a %Y-%m-%d %I:%M %p}  [{m.tier:>4}] {m.title():45} {flag:9} {m.key}")
    save_state(st)
    return 0


def cmd_sync(cfg: dict, args) -> int:
    st = load_state()
    meetings = gather(cfg, st, args)
    created, err = write_calendar(cfg, st, meetings, args.dry_run)
    today = datetime.now(TZ).date().isoformat()
    if err:
        print(f"calendar: {err}", file=sys.stderr)
        if st["notices"].get("auth") != today and not args.dry_run:
            st["notices"]["auth"] = today
            notify("(o.o) KC Civic found meetings but has no calendar token yet. Run kc-civic auth-calendar.",
                   "console", err)
    else:
        mark_vanished(cfg, st, {m.key for m in meetings}, args.dry_run)
        drop_stale_holds(cfg, st, {m.key for m in meetings}, args.dry_run)
    preps = []
    if not args.no_prep and not args.dry_run:
        for m in prep_candidates(cfg, st, meetings)[: cfg["prep_max_per_pass"]]:
            if m.extra.get("pages") and (datetime.now().timestamp() - float(st.get("last_edc", 0))) / 3600 > 2:
                continue  # walled-page work waits for the daily browser pass
            rec = do_prep(cfg, st, m)
            save_state(st)
            if rec:
                preps.append((m, rec))
        if preps and not err:
            write_calendar(cfg, st, [m for m, _ in preps], False)
    save_state(st)
    if preps or created:
        parts = []
        if created:
            parts.append(f"{len(created)} new meeting(s) on the calendar: " + "; ".join(created[:6]))
        for m, rec in preps:
            s = rec["summary"]
            parts.append(f"{m.start:%a %-m/%-d} {m.short}: {s.get('verdict', '?')}. {s.get('headline', '')}")
        link = obsidian_link(Path(preps[0][1]["note"])) if preps else "console"
        notify("(o.o) " + " | ".join(parts), link, "kc-civic sync digest\n" + "\n".join(parts))
    return 0


def cmd_prep(cfg: dict, args) -> int:
    st = load_state()
    meetings = gather(cfg, st, args)
    m = next((x for x in meetings if x.key == args.key), None)
    if m is None:
        print(f"no meeting {args.key} in the next {cfg['sync_days']} days", file=sys.stderr)
        return 2
    if not args.force and st["prepped"].get(m.key, {}).get("fingerprint") == m.agenda_fingerprint:
        print(f"already prepped: {st['prepped'][m.key]['note']}")
        return 0
    rec = do_prep(cfg, st, m)
    save_state(st)
    if not rec:
        return 1
    try:
        write_calendar(cfg, st, [m], False)
    except RuntimeError as e:
        print(f"calendar: {e}", file=sys.stderr)
    save_state(st)
    print(rec["note"])
    print(json.dumps(rec["summary"], indent=2))
    return 0


def cmd_auth(cfg: dict, args) -> int:
    if args.code:
        print(f"token written: {gcal.exchange(args.code)}")
        return 0
    print("Open this URL, approve, then run: kc-civic auth-calendar --code '<redirected URL>'\n")
    print(gcal.consent_url())
    return 0


def cmd_status(cfg: dict, args) -> int:
    st = load_state()
    print(f"calendar token: {'present' if gcal.TOKEN_PATH.exists() else 'MISSING'}")
    last = float(st.get("last_edc", 0))
    print(f"last EDC fetch: {datetime.fromtimestamp(last):%Y-%m-%d %H:%M}" if last else "last EDC fetch: never")
    print(f"synced meetings: {len(st['synced'])}; prepped: {len(st['prepped'])}")
    for _k, r in sorted(st["prepped"].items(), key=lambda kv: kv[1].get("at", "")):
        print(f"  {r.get('at', '')[:16]}  {r['summary'].get('verdict', '?'):16} {Path(r['note']).name}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="kc-civic", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("list")
    sp.add_argument("--no-edc", action="store_true")
    sp.add_argument("--force-edc", action="store_true")
    sp.add_argument("--no-holds", action="store_true")
    sp.set_defaults(fn=cmd_list)
    sp = sub.add_parser("sync")
    for f in ("--no-edc", "--force-edc", "--no-prep", "--dry-run", "--no-holds"):
        sp.add_argument(f, action="store_true")
    sp.set_defaults(fn=cmd_sync)
    sp = sub.add_parser("prep")
    sp.add_argument("key")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--no-edc", action="store_true")
    sp.set_defaults(fn=cmd_prep)
    sp = sub.add_parser("auth-calendar")
    sp.add_argument("--code")
    sp.set_defaults(fn=cmd_auth)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = p.parse_args()
    return args.fn(load_config(), args)


if __name__ == "__main__":
    raise SystemExit(main())
