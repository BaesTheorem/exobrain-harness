"""Send the EDC board meetings (TIF Commission, PIEA, LCRA) to the Common Lot
site, which cannot read edckc.com itself (the site answers bots with a
challenge). Called after each live EDC read. The endpoint and token are in
secrets/common-lot.json (gitignored): {"endpoint": "...", "token": "..."}.
A failure is printed and ignored: the calendar sync must not depend on it.
"""
import hashlib
import json
import sys
import urllib.request
from datetime import timezone
from pathlib import Path

from .model import Meeting

SECRETS = Path(__file__).resolve().parent.parent / "secrets" / "common-lot.json"


# The site's body list (site/content/bodies.json in common-lot) names the boards in full.
FULL = {"TIF Commission": "Tax Increment Financing Commission (TIF Commission)",
        "PIEA Board": "Planned Industrial Expansion Authority (PIEA)",
        "LCRA Board": "Land Clearance for Redevelopment Authority (LCRA)"}


def _row(m: Meeting) -> dict:
    uid = hashlib.sha256((m.source_id or m.key).encode()).hexdigest()[:12]
    utc = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"id": f"E{uid}", "body": FULL.get(m.short, m.body), "bodyId": None, "bodyType": "EDC board", "start": utc(m.start), "end": utc(m.end),
            "timeKnown": True, "location": m.location, "cancelled": m.cancelled, "agenda": m.agenda_url or None, "minutes": None,
            "video": None, "detail": m.url or None, "zoom": m.join_link or None, "note": "", "source": "EDC calendar (edckc.com)"}


def push(meetings: list[Meeting]) -> None:
    if not SECRETS.exists():
        return
    cfg = json.loads(SECRETS.read_text())
    body = json.dumps({"meetings": [_row(m) for m in meetings if m.source == "edc"]}).encode()
    req = urllib.request.Request(cfg["endpoint"], data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['token']}",
                                          "User-Agent": "kc-civic/1.0 (Common Lot EDC sync)"})  # Cloudflare refuses Python's default agent
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"common lot: {json.load(r)}")
    except Exception as e:  # noqa: BLE001 - never break the sync over the website
        print(f"common lot push failed: {e}", file=sys.stderr)
