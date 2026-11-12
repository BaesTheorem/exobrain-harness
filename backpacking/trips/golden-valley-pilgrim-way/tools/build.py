"""Build the GVPW 8-night plan: build/site/index.html (MapLibre page) and build/site/gvpw-8-night.gpx.

Inputs: src/route7.json (official Deanery OS Maps line), build/sites_measured.json (sites measured by
sites.py), src/side.json (detours routed by route_side.py), src/plan.json (days, notes, wells).
"""
import html
import json

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "src/route7.json").read_text())
S = json.loads((ROOT / "build/sites_measured.json").read_text())
SIDE = json.loads((ROOT / "src/side.json").read_text())
PLAN = json.loads((ROOT / "src/plan.json").read_text())
OUT = ROOT / "build/site"
OUT.mkdir(parents=True, exist_ok=True)

line, cum = R["line"], S["cum"]
sites = {s["id"]: s for s in S["sites"]}
for w in PLAN.get("extra_sites", []):
    sites[w["id"]] = w


def idx_at(km: float) -> int:
    return min(range(len(cum)), key=lambda i: abs(cum[i] - km))


def climb(a: float, b: float) -> tuple[int, int]:
    pts = [p for p in R["wps"] if a - 0.01 <= p[2] <= b + 0.01]
    up = dn = 0.0
    ref = pts[0][3]
    for p in pts[1:]:
        d = p[3] - ref
        if d >= 3:
            up += d
            ref = p[3]
        elif d <= -3:
            dn -= d
            ref = p[3]
    return round(up), round(dn)


days = []
for d in PLAN["days"]:
    a, b = sites[d["from"]]["km"], sites[d["to"]]["km"]
    i, j = idx_at(a), idx_at(b)
    up, dn = climb(a, b)
    side_km = sum(SIDE[k]["km"] for k in d.get("side", [])) + d.get("side_km_manual", 0)
    days.append({**d, "km": round(b - a, 1), "side_km": round(side_km, 1), "up": up, "dn": dn,
                 "line": line[i:j + 1],
                 "profile": [[round(p[2] - a, 2), round(p[3])] for p in R["wps"] if a - 0.01 <= p[2] <= b + 0.01]})

def outbound(ln: list) -> list:
    """Out-and-back detours: keep only the leg out to the farthest point, so the dots do not overlap."""
    a = ln[0]
    far = max(range(len(ln)), key=lambda i: (ln[i][0] - a[0]) ** 2 + ((ln[i][1] - a[1]) * 1.6) ** 2)
    return ln[: far + 1]


for v in SIDE.values():
    v["out"] = outbound(v["line"])

data = {
    "days": days,
    "side": {k: v for k, v in SIDE.items() if any(k in d.get("side", []) for d in days) or k in PLAN.get("optional_side", [])},
    "optional_side": PLAN.get("optional_side", []),
    "sites": [s for s in sites.values() if s.get("show", True)],
    "meta": PLAN["meta"],
}

# GPX: one track per day, detours as their own tracks, every shown site as a waypoint.
def trk(name: str, pts: list) -> str:
    seg = "".join(f'<trkpt lat="{p[1]:.6f}" lon="{p[0]:.6f}"/>' for p in pts)
    return f"<trk><name>{html.escape(name)}</name><trkseg>{seg}</trkseg></trk>\n"


gpx = ['<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="exobrain-harness" xmlns="http://www.topografix.com/GPX/1/1">\n']
for s in data["sites"]:
    gpx.append(f'<wpt lat="{s["lat"]}" lon="{s["lon"]}"><name>{html.escape(s["name"])}</name><type>{s["kind"]}</type></wpt>\n')
for d in days:
    gpx.append(trk(d["title"], d["line"]))
for k, v in data["side"].items():
    gpx.append(trk(PLAN["side_names"].get(k, k), v["line"]))
gpx.append("</gpx>\n")
(OUT / "gvpw-8-night.gpx").write_text("".join(gpx))

tpl = (ROOT / "tools/page.html").read_text()
(OUT / "index.html").write_text(tpl.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))))
tot = sum(d["km"] for d in days)
side = sum(d["side_km"] for d in days)
print(f"route {tot:.1f} km + detours {side:.1f} km = {tot + side:.1f} km ({(tot + side) / 1.609:.1f} mi)")
for d in days:
    print(f'{d["title"]:48} {d["km"]:5.1f} km +{d["side_km"]:.1f} side  +{d["up"]} m')

