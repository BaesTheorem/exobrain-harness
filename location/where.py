#!/usr/bin/env python3
"""Where Alex went on a day, built from GPS points.

Sources (both land in the same point format, see receiver.py):
  location/data/points/         live points from the Overland receiver
  location/data/points-google/  points converted from a Google Maps
                                Timeline export (location-history.json)

Usage:
  where.py [YYYY-MM-DD|today|yesterday] [--json]
  where.py import-google FILE

A day becomes a sequence of stays (time inside a small radius) and moves
(the travel between them), plus gaps where there is no data. Stays get a
name from, in order: Home (MYKCMO_HOME_LAT/LON in the harness .env), the
gitignored data/places.json ([{"name", "lat", "lon", "radius_m"}]), then a
cached Nominatim reverse geocode.

INVARIANTS:
  - A gap is "no data", never "stayed home". The output must say which hours
    have no points so a missing day is not read as a quiet day.
  - Nominatim gets at most one request per second, and every answer is
    cached in data/geocache.json.
"""

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS_DIR = HERE.parent
DATA = HERE / "data"
SOURCES = [DATA / "points", DATA / "points-google"]
PLACES_FILE = DATA / "places.json"
GEOCACHE_FILE = DATA / "geocache.json"

STAY_RADIUS_M = 150
STAY_MIN = timedelta(minutes=10)
GAP_MIN = timedelta(minutes=90)
MAX_ACCURACY_M = 200
UA = "exobrain-harness-where/1.0 (personal location log)"


def load_env():
    env_path = HARNESS_DIR / ".env"
    if not env_path.exists():
        return {}
    out = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------- loading ----------


def load_points(day, sources=None):
    """All points for a local date, sorted, one per timestamp, with
    low-precision fixes removed."""
    seen = {}
    for src in sources or SOURCES:
        f = src / f"{day}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            acc = (rec.get("p") or {}).get("horizontal_accuracy")
            if isinstance(acc, (int, float)) and acc > MAX_ACCURACY_M:
                continue
            rec["dt"] = datetime.fromisoformat(rec["t"])
            seen.setdefault(rec["t"], rec)
    return sorted(seen.values(), key=lambda r: r["dt"])


# ---------- segmentation ----------


def segment(points):
    """Split points into stays and moves. A stay starts at a point and
    takes every following point within STAY_RADIUS_M of the running
    centroid; it counts if it lasts STAY_MIN. Everything between stays is a
    move. Returns a list of dicts with kind, start, end and the points."""
    segs = []
    i, n = 0, len(points)
    pending = []
    while i < n:
        lat, lon, k = points[i]["lat"], points[i]["lon"], 1
        j = i + 1
        while j < n and haversine_m(lat, lon, points[j]["lat"], points[j]["lon"]) <= STAY_RADIUS_M:
            lat += (points[j]["lat"] - lat) / (k + 1)
            lon += (points[j]["lon"] - lon) / (k + 1)
            k += 1
            j += 1
        if points[j - 1]["dt"] - points[i]["dt"] >= STAY_MIN:
            if pending:
                segs.append(_move(pending + [points[i]]))
                pending = []
            segs.append({"kind": "stay", "start": points[i]["dt"], "end": points[j - 1]["dt"],
                         "lat": lat, "lon": lon, "points": j - i})
            pending = [points[j - 1]]
            i = j
        else:
            pending.append(points[i])
            i += 1
    if len(pending) > 1:
        segs.append(_move(pending))
    return _split_gaps(segs)


def _move(pts):
    dist = sum(haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in pairwise(pts))
    motions = {}
    for p in pts:
        for m in (p.get("p") or {}).get("motion") or []:
            if m != "stationary":
                motions[m] = motions.get(m, 0) + 1
    mode = max(motions, key=lambda m: motions[m]) if motions else ""
    return {"kind": "move", "start": pts[0]["dt"], "end": pts[-1]["dt"], "meters": dist,
            "mode": mode, "points": len(pts), "pts": pts}


def _split_gaps(segs):
    """Mark long silences inside moves as gaps. A stay with a long silence
    keeps it (both ends were at the same place), but it is flagged."""
    out = []
    for s in segs:
        if s["kind"] != "move":
            out.append(s)
            continue
        pts = s.pop("pts")
        run = [pts[0]]
        for a, b in pairwise(pts):
            if b["dt"] - a["dt"] >= GAP_MIN:
                if len(run) > 1:
                    out.append(_move(run))
                out.append({"kind": "gap", "start": a["dt"], "end": b["dt"]})
                run = [b]
            else:
                run.append(b)
        if len(run) > 1:
            out.append(_move(run))
    for s in out:
        s.pop("pts", None)
    return [s for s in out if s["kind"] != "move" or s["end"] > s["start"]]


# ---------- naming ----------


def _load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


_last_nominatim = [0.0]


def reverse_geocode(lat, lon, cache):
    key = f"{lat:.4f},{lon:.4f}"
    if key in cache:
        return cache[key]
    wait = 1.1 - (time.time() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/reverse?{q}",
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except (OSError, ValueError):
        return None
    finally:
        _last_nominatim[0] = time.time()
    addr = data.get("address") or {}
    street = " ".join(x for x in (addr.get("house_number"), addr.get("road")) if x)
    name = data.get("name") or ""
    label = ", ".join(x for x in (name, street) if x) or data.get("display_name", "")[:60]
    cache[key] = label
    return label


def name_stays(segs, env, offline=False):
    places = _load_json(PLACES_FILE, [])
    try:
        places.insert(0, {"name": "Home", "lat": float(env["MYKCMO_HOME_LAT"]),
                          "lon": float(env["MYKCMO_HOME_LON"]), "radius_m": STAY_RADIUS_M})
    except (KeyError, ValueError):
        pass
    cache = _load_json(GEOCACHE_FILE, {})
    for s in segs:
        if s["kind"] != "stay":
            continue
        for p in places:
            if haversine_m(s["lat"], s["lon"], p["lat"], p["lon"]) <= p.get("radius_m", STAY_RADIUS_M):
                s["place"] = p["name"]
                break
        else:
            label = None if offline else reverse_geocode(s["lat"], s["lon"], cache)
            s["place"] = label or f"{s['lat']:.4f}, {s['lon']:.4f}"
    if not offline:
        GEOCACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GEOCACHE_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True))


# ---------- output ----------


def _hm(td):
    m = int(td.total_seconds() // 60)
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def summarize(day, points, segs):
    stays = [s for s in segs if s["kind"] == "stay"]
    moves = [s for s in segs if s["kind"] == "move"]
    gaps = [s for s in segs if s["kind"] == "gap"]
    away = sum((s["end"] - s["start"] for s in stays if s.get("place") != "Home"), timedelta())
    home = sum((s["end"] - s["start"] for s in stays if s.get("place") == "Home"), timedelta())
    return {
        "date": day,
        "points": len(points),
        "first": points[0]["dt"].strftime("%H:%M") if points else None,
        "last": points[-1]["dt"].strftime("%H:%M") if points else None,
        "km": round(sum(m["meters"] for m in moves) / 1000, 1),
        "home": _hm(home),
        "away_at_places": _hm(away),
        "left_home": any(s.get("place") != "Home" for s in stays) or bool(moves),
        "segments": [
            {"kind": s["kind"], "start": s["start"].strftime("%H:%M"), "end": s["end"].strftime("%H:%M"),
             "duration": _hm(s["end"] - s["start"]),
             **({"place": s.get("place")} if s["kind"] == "stay" else {}),
             **({"km": round(s["meters"] / 1000, 1), "mode": s["mode"]} if s["kind"] == "move" else {})}
            for s in segs
        ],
        "gaps": [f"{g['start']:%H:%M}-{g['end']:%H:%M}" for g in gaps],
    }


def render(summary):
    if not summary["points"]:
        return f"No GPS points for {summary['date']}. Overland has not synced, or the phone was off."
    lines = [f"GPS {summary['date']}: {summary['points']} points, {summary['first']} to {summary['last']}, "
             f"{summary['km']} km moved, {summary['home']} at home."]
    for s in summary["segments"]:
        if s["kind"] == "stay":
            lines.append(f"- {s['start']}-{s['end']} {s['place']} ({s['duration']})")
        elif s["kind"] == "move":
            mode = f" {s['mode']}" if s["mode"] else ""
            lines.append(f"- {s['start']}-{s['end']}{mode} {s['km']} km ({s['duration']})")
        else:
            lines.append(f"- {s['start']}-{s['end']} no data ({s['duration']})")
    return "\n".join(lines)


# ---------- Google Timeline import ----------

_GEO_RE = re.compile(r"(-?\d+(?:\.\d+)?)°?,\s*(-?\d+(?:\.\d+)?)")


def _latlng(v):
    """Google writes "geo:39.06,-94.58" (iOS) or "39.06°, -94.58°" (Android),
    sometimes wrapped as {"latLng": ...}."""
    if isinstance(v, dict):
        v = v.get("latLng") or v.get("point") or ""
    m = _GEO_RE.search(str(v).removeprefix("geo:"))
    return (float(m.group(1)), float(m.group(2))) if m else None


def google_points(data):
    """Yield point records from a Google Timeline export, either format."""
    segs = data.get("semanticSegments", []) if isinstance(data, dict) else data
    for seg in segs:
        start = seg.get("startTime")
        end = seg.get("endTime")
        if not start:
            continue
        t0 = datetime.fromisoformat(start).astimezone()
        t1 = datetime.fromisoformat(end).astimezone() if end else t0
        if "visit" in seg:
            ll = _latlng((seg["visit"].get("topCandidate") or {}).get("placeLocation"))
            if ll:
                for t in (t0, t1):
                    yield {"t": t.isoformat(), "lat": ll[0], "lon": ll[1], "p": {"source": "google-visit"}}
        if "activity" in seg:
            act = seg["activity"]
            mode = ((act.get("topCandidate") or {}).get("type") or "").lower()
            for t, key in ((t0, "start"), (t1, "end")):
                ll = _latlng(act.get(key))
                if ll:
                    yield {"t": t.isoformat(), "lat": ll[0], "lon": ll[1],
                           "p": {"source": "google-activity", "motion": [mode] if mode else []}}
        for pt in seg.get("timelinePath") or []:
            ll = _latlng(pt.get("point"))
            if not ll:
                continue
            if pt.get("time"):
                t = datetime.fromisoformat(pt["time"]).astimezone()
            else:
                t = t0 + timedelta(minutes=float(pt.get("durationMinutesOffsetFromStartTime") or 0))
            yield {"t": t.isoformat(), "lat": ll[0], "lon": ll[1], "p": {"source": "google-path"}}


def import_google(path):
    data = json.loads(Path(path).read_text())
    by_day = {}
    for rec in google_points(data):
        by_day.setdefault(rec["t"][:10], {})[rec["t"]] = rec
    out_dir = DATA / "points-google"
    out_dir.mkdir(parents=True, exist_ok=True)
    for day, recs in by_day.items():
        (out_dir / f"{day}.jsonl").write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for _, r in sorted(recs.items())))
    days = sorted(by_day)
    print(f"imported {sum(len(r) for r in by_day.values())} points over {len(days)} days"
          + (f" ({days[0]} to {days[-1]})" if days else ""))


# ---------- CLI ----------


def parse_day(s):
    if s in (None, "today"):
        return date.today().isoformat()
    if s == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return date.fromisoformat(s).isoformat()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["import-google"]:
        if len(argv) != 2:
            sys.exit("usage: where.py import-google location-history.json")
        import_google(argv[1])
        return
    ap = argparse.ArgumentParser(description="Where Alex went on a day, from GPS points.")
    ap.add_argument("day", nargs="?", help="YYYY-MM-DD, today (default), or yesterday")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--offline", action="store_true", help="skip reverse geocoding")
    args = ap.parse_args(argv)
    day = parse_day(args.day)
    points = load_points(day)
    segs = segment(points)
    name_stays(segs, load_env(), offline=args.offline)
    summary = summarize(day, points, segs)
    print(json.dumps(summary, indent=1) if args.json else render(summary))


if __name__ == "__main__":
    main()
