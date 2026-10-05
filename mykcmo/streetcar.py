"""KC Streetcar reports. The Authority is not part of 311.

Its contact page lists three equal channels: phone 816-627-2527, email
info@kcstreetcar.org, and an embedded Google Form ("KC Streetcar Comment
Form"). Email is the default here: it is the canonical inbox, it carries
photos, and replies come back to the sender. The form is the second channel:
its responses go to whichever Google account owns it, which is not visible
from outside, and it takes no attachments. Google Forms accept a plain POST
to /formResponse with `entry.<id>` fields and no login.

Checked 2026-10-05: an empty POST returns HTTP 400 with "This is a required
question" for the five required fields, and records nothing. A complete POST
returns 200 with "Your response has been recorded".

INVARIANTS:
- submit() is the only function that posts, and only its caller's
  confirm=True gate reaches it.
- If the form changes (new entry ids), fetch_fields() shows the new ids;
  the submit check fails loudly instead of posting to stale fields.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime

import kcplace as geo

FORM = "https://docs.google.com/forms/d/e/1FAIpQLSfhaRGEGqAlQGotd2BJumLwN6EyD3nfJHSvmAYCZ_EtSYWOoA"
EMAIL_FALLBACK = "info@kcstreetcar.org"
PHONE = "816-627-2527"
# See Say (ELERTS): reports go straight to a KC Streetcar dispatcher, with
# two-way text. App, text line, or web (TellKCStreetcar.com). The web form is
# behind Cloudflare Turnstile, so it is for a person in a browser; the text
# line is the scriptable path.
SEE_SAY_SMS = "816-837-4800"
SEE_SAY_WEB = "https://tellkcstreetcar.com"
# Issue kinds that belong with dispatch (on board or at a stop, now).
DISPATCH_KINDS = ("safety", "security", "maintenance", "clean", "trash", "glass", "graffiti", "vandal", "behavior",
                  "harass", "suspicious", "intox", "sleep", "loiter")

ENTRY = {
    "name": "entry.1443158304",
    "email": "entry.30154506",
    "phone": "entry.1654076803",
    "date": "entry.1431104716",
    "time": "entry.1274736842",
    "location": "entry.1283678138",
    "car": "entry.896449910",
    "staff": "entry.393971458",
    "description": "entry.1849504893",
    "comment": "entry.794652799",
}

# Stop names as the Authority's See Say form writes them; positions from
# OpenStreetMap (railway=tram_stop, data (c) OpenStreetMap contributors, ODbL),
# averaged over each stop's two platforms. North to south.
STOPS = [
    ("Riverfront (Berkley Riverfront)", 39.11715, -94.57212), ("River Market (3rd & Grand)", 39.11043, -94.58133),
    ("River Market West (4th & Delaware)", 39.10880, -94.58438), ("City Market (5th & Walnut)", 39.10851, -94.58189),
    ("North Loop (7th & Main)", 39.10524, -94.58303), ("Library (9th & Main)", 39.10311, -94.58307),
    ("Metro Center (12th & Main)", 39.09994, -94.58321), ("Power & Light (14th & Main)", 39.09684, -94.58334),
    ("Kauffman Center (16th & Main)", 39.09451, -94.58347), ("Crossroads (19th & Main)", 39.09041, -94.58368),
    ("Union Station (Pershing & Main)", 39.08467, -94.58406), ("WWI Museum & Memorial (27th & Main)", 39.07853, -94.58453),
    ("Union Hill (31st & Main)", 39.07107, -94.58531), ("Armour (35th & Main)", 39.06377, -94.58569),
    ("Westport (39th & Main)", 39.05643, -94.58612), ("Southmoreland (43rd & Main)", 39.04937, -94.58655),
    ("Art Museums (45th & Main)", 39.04591, -94.58674), ("Plaza (Cleaver II & Brookside)", 39.04109, -94.58612),
    ("UMKC (51st & Brookside)", 39.03547, -94.58412),
]


def nearest_stop(lat: float, lon: float) -> tuple[str, float]:
    name, slat, slon = min(STOPS, key=lambda s: geo.meters(lat, lon, s[1], s[2]))
    return name, geo.meters(lat, lon, slat, slon)


def location_text(lat: float, lon: float, source: str) -> str:
    stop, dist = nearest_stop(lat, lon)
    place = geo.describe(lat, lon, source)
    near = f"{stop} stop" if dist <= 150 else f"between stops, {round(dist)} m from the {stop} stop"
    return f"{near}. {place['line'].removeprefix('Location: ')}"


def email_draft(*, when: datetime, location: str, car: str, description: str, kind: str = "Issue",
                contact: dict | None = None, has_photo: bool = False) -> dict:
    """Subject and body for an email to the Authority's canonical inbox."""
    stop = location.split(".")[0]
    lines = [
        "Hello,",
        "",
        f"I want to report a problem I saw on {when.strftime('%A, %B %-d, %Y')} at about {when.strftime('%-I:%M %p')}.",
        "",
        description.strip(),
        "",
        f"Location: {location}",
    ]
    if car and car.upper() != "NA":
        lines.append(f"Streetcar number: {car}")
    if has_photo:
        lines += ["", "A photo is attached."]
    lines += ["", "Please let me know if you need more details."]
    c = contact or {}
    sig = [x for x in (f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(), c.get("phone", ""), c.get("email", "")) if x]
    if sig:
        lines += ["", "Thank you,", *sig]
    return {"to": EMAIL_FALLBACK, "subject": f"[Issue Report] {kind} - {stop}", "body": "\n".join(lines)}


def sms_draft(*, location: str, car: str, description: str, kind: str) -> dict:
    """A See Say text to dispatch: short, the location first."""
    where = location.split(". GPS")[0]
    gps = location.split("GPS ")[1].split(" (")[0] if "GPS " in location else ""
    car_part = f" Car {car}." if car and car.upper() != "NA" else ""
    body = f"{kind}: {description.strip()} At {where}.{car_part}" + (f" GPS {gps}." if gps else "")
    return {"to": SEE_SAY_SMS, "body": body}


def recommended_channel(kind: str) -> str:
    k = kind.lower()
    return "see_say" if any(w in k for w in DISPATCH_KINDS) else "email"


def fetch_fields() -> list[dict]:
    """The live form's questions and entry ids (to detect a changed form)."""
    req = urllib.request.Request(FORM + "/viewform", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode()
    m = re.search(r"FB_PUBLIC_LOAD_DATA_ = (.*?);</script>", page, re.S)
    if not m:
        raise RuntimeError("Could not read the streetcar form; it may have moved.")
    data = json.loads(m.group(1))
    return [{"title": item[1], "entry": f"entry.{e[0]}", "required": bool(e[2])}
            for item in data[1][1] for e in (item[4] or [])]


def build(*, email: str, when: datetime, location: str, car: str, description: str, comment: str = "",
          name: str = "", phone: str = "", staff: str = "") -> dict[str, str]:
    d = when.strftime
    return {
        ENTRY["name"]: name, ENTRY["email"]: email, ENTRY["phone"]: phone,
        f"{ENTRY['date']}_year": d("%Y"), f"{ENTRY['date']}_month": d("%m"), f"{ENTRY['date']}_day": d("%d"),
        f"{ENTRY['time']}_hour": d("%H"), f"{ENTRY['time']}_minute": d("%M"),
        ENTRY["location"]: location, ENTRY["car"]: car or "NA", ENTRY["staff"]: staff,
        ENTRY["description"]: description, ENTRY["comment"]: comment,
    }


def submit(fields: dict[str, str]) -> dict:
    """POST the form. This sends a REAL comment to the KC Streetcar Authority."""
    live = {f["entry"] for f in fetch_fields()}
    stale = {k.split("_")[0] for k in fields} - live
    if stale:
        raise RuntimeError(f"The streetcar form changed (unknown fields {sorted(stale)}). Update streetcar.ENTRY.")
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(FORM + "/formResponse", data=body, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode(errors="ignore")
            code = r.status
    except urllib.error.HTTPError as e:
        page, code = e.read().decode(errors="ignore"), e.code
    ok = code == 200 and "response has been recorded" in page
    missing = page.count("This is a required question")
    return {"ok": ok, "http": code, "missing_required": missing}
