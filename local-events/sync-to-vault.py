#!/usr/bin/env python3
"""Project the local-events JSON log into per-event Obsidian notes for the Local Events Base.

The JSON log (local-events-log.json) is the canonical store written by the /local-events
skill. This script is a pure projection: it (re)writes one markdown note per event into the
vault's "Local Events/" folder so that "Local Events.base" can render live table/card views.

Idempotent: the target folder is fully regenerated each run, so notes carry no manual data.
Events older than RETAIN_PASSED_DAYS are dropped so the folder stays small.

Usage:  python3 sync-to-vault.py
Run this after every /local-events scan (the skill does this automatically).
"""
import json
import os
import re
import datetime

LOG = os.path.join(os.path.dirname(__file__), "local-events-log.json")
VAULT_FOLDER = "/Users/alexhedtke/Exobrain/Local Events"
RETAIN_PASSED_DAYS = 45  # keep recently-passed events so the "Passed" view has context

ILLEGAL = re.compile(r'[\\/:#^\[\]|*?"<>]')


def slug(name, date):
    base = ILLEGAL.sub(" ", name).strip()
    base = re.sub(r"\s+", " ", base)
    return f"{base[:80]} ({date})"


def yaml_str(v):
    """Quote a scalar for YAML frontmatter."""
    if v is None or v == "":
        return '""'
    s = str(v).replace('"', "'")
    return f'"{s}"'


def is_streetcar(ev):
    blob = (ev.get("notes", "") + " " + (ev.get("venue") or "")).lower()
    return any(k in blob for k in ("streetcar", "walkable", "union station", "crossroads", "crown center"))


def main():
    with open(LOG) as f:
        events = json.load(f)

    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=RETAIN_PASSED_DAYS)

    os.makedirs(VAULT_FOLDER, exist_ok=True)
    # Wipe prior projections (only .md files; never touch anything else)
    for fn in os.listdir(VAULT_FOLDER):
        if fn.endswith(".md"):
            os.remove(os.path.join(VAULT_FOLDER, fn))

    written = 0
    for ev in events:
        date_s = ev.get("date") or ""
        try:
            d = datetime.date.fromisoformat(date_s)
        except ValueError:
            d = None
        # Keep: undated, future, or recently-passed events. Drop ancient history.
        if d is not None and d < cutoff:
            continue

        name = ev.get("name", "Untitled event")
        fav = bool(ev.get("favoriteArtist") or ev.get("favorite_artist"))
        cost = ev.get("cost") or "unknown"

        fm = [
            "---",
            "type: local-event",
            f"event_date: {date_s}" if date_s else "event_date: ",
            f"time: {yaml_str(ev.get('time'))}",
            f"venue: {yaml_str(ev.get('venue'))}",
            f"address: {yaml_str(ev.get('address'))}",
            f"cost: {yaml_str(cost)}",
            f"priority: {yaml_str(ev.get('priority'))}",
            f"status: {yaml_str(ev.get('status'))}",
            f"source: {yaml_str(ev.get('source'))}",
            f"streetcar: {str(is_streetcar(ev)).lower()}",
            f"favorite_artist: {str(fav).lower()}",
            f"url: {yaml_str(ev.get('url'))}",
            f"ticket_url: {yaml_str(ev.get('ticketUrl'))}",
            f"first_seen: {yaml_str(ev.get('firstSeen'))}",
            f"last_surfaced: {yaml_str(ev.get('lastSurfaced'))}",
            f"event_id: {yaml_str(ev.get('id'))}",
            "---",
        ]
        body = []
        why = ev.get("notes", "")
        if why:
            body.append(f"**Why:** {why}")
            body.append("")
        links = []
        if ev.get("url"):
            links.append(f"[Event page]({ev['url']})")
        if ev.get("ticketUrl"):
            links.append(f"[Tickets]({ev['ticketUrl']})")
        if links:
            body.append(" · ".join(links))

        note = "\n".join(fm) + "\n" + "\n".join(body) + "\n"
        path = os.path.join(VAULT_FOLDER, slug(name, date_s or "undated") + ".md")
        with open(path, "w") as f:
            f.write(note)
        written += 1

    print(f"Synced {written} event notes to {VAULT_FOLDER}")


if __name__ == "__main__":
    main()
