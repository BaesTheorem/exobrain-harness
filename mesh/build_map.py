# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "matplotlib", "tifffile", "playwright"]
# ///
"""Build an interactive terrain map and line-of-sight table for a LoRa mesh.

Reads a site list (sites.json, gitignored: it holds friends' names and
addresses), downloads a USGS 3DEP bare-earth grid for the box once, and
writes into the site list's out_dir:

  map.html        MapLibre map: elevation tint + hillshade, 10 ft contours,
                  every link colored by terrain clearance, click a link for
                  its elevation profile, optional 3D terrain.
  map.png         a static render of map.html for embedding in a note.
  profiles.png    elevation profile from the first site to every other site.
  links.json      the computed table (clearance, Fresnel, bearing, window).

Usage: uv run mesh/build_map.py [sites.json] [--no-png]

INVARIANTS
- Never write site data anywhere in the repo: outputs go to out_dir only.
- Clearance is bare earth at 4/3 earth radius. Trees and buildings are not
  included, so "clear" is an upper bound on what the radio sees.
"""

import base64
import io
import itertools
import json
import math
import sys
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import tifffile  # noqa: E402
from PIL import Image  # noqa: E402

HERE = Path(__file__).resolve().parent
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
FREQ_GHZ = 0.915
K_FACTOR = 4 / 3
EARTH_R_M = 6_371_000
M_TO_FT = 3.28084
# Sequential blue ramp (dataviz reference palette, steps 100 -> 650): light = low.
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
        "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281"]
STATUS = {"clear": "#0ca30c", "marginal": "#fab219", "blocked": "#d03b3b"}
COMPASS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def floor_to_agl_ft(floor: float) -> float:
    """Window height above ground: 10 ft per story, sill mid-floor."""
    return 10 * (floor - 1) + 5


def fetch_dem(bbox: list[float], path: Path) -> None:
    w, s, e, n = bbox
    # Approximately 5 m per pixel; the ImageServer caps a request at 4000 px.
    cols = min(4000, round((e - w) * 111_320 * math.cos(math.radians((s + n) / 2)) / 5))
    rows = min(4000, round((n - s) * 110_540 / 5))
    url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/"
           f"ImageServer/exportImage?bbox={w},{s},{e},{n}&bboxSR=4326&imageSR=4326"
           f"&size={cols},{rows}&format=tiff&pixelType=F32"
           "&interpolation=RSP_BilinearInterpolation&f=image")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=120) as r:
        path.write_bytes(r.read())


class Dem:
    def __init__(self, path: Path):
        # The server keeps pixels square and grows the box to fit, so the
        # requested bbox is not the real extent. Read it from the GeoTIFF tags.
        with tifffile.TiffFile(path) as tif:
            page = tif.pages[0]
            self.z = page.asarray().astype(float) * M_TO_FT  # feet
            sx, sy, _ = page.tags["ModelPixelScaleTag"].value
            _, _, _, self.w, self.n, _ = page.tags["ModelTiepointTag"].value
        self.rows, self.cols = self.z.shape
        self.sx, self.sy = sx, sy
        self.e = self.w + sx * self.cols
        self.s = self.n - sy * self.rows

    def at(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Bilinear sample in feet."""
        x = (lon - self.w) / self.sx - 0.5  # pixel-is-area: centers sit half a pixel in
        y = (self.n - lat) / self.sy - 0.5
        x0 = np.clip(np.floor(x).astype(int), 0, self.cols - 2)
        y0 = np.clip(np.floor(y).astype(int), 0, self.rows - 2)
        fx, fy = x - x0, y - y0
        z = self.z
        return (z[y0, x0] * (1 - fx) * (1 - fy) + z[y0, x0 + 1] * fx * (1 - fy)
                + z[y0 + 1, x0] * (1 - fx) * fy + z[y0 + 1, x0 + 1] * fx * fy)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def window_check(site: dict, brg: float) -> str:
    f = site.get("facing", "?")
    if f == "all":
        return "window"
    if f not in COMPASS:
        return "unknown"
    diff = abs((brg - COMPASS[f] + 180) % 360 - 180)
    return "window" if diff <= 67.5 else "through building"


def link(dem: Dem, a: dict, b: dict, n: int = 400) -> dict:
    d_m = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
    t = np.linspace(0, 1, n)
    ground = dem.at(a["lat"] + (b["lat"] - a["lat"]) * t, a["lon"] + (b["lon"] - a["lon"]) * t)
    d1 = t * d_m
    d2 = d_m - d1
    bulge = d1 * d2 / (2 * K_FACTOR * EARTH_R_M) * M_TO_FT
    za = ground[0] + a["agl_ft"]
    zb = ground[-1] + b["agl_ft"]
    ray = za + (zb - za) * t
    # First Fresnel radius (m) = 17.32 * sqrt(d1 d2 / (f D)), d in km, f in GHz.
    f1 = 17.32 * np.sqrt((d1 / 1000) * (d2 / 1000) / (FREQ_GHZ * d_m / 1000 + 1e-9)) * M_TO_FT
    obstacle = ground + bulge
    clear = ray - obstacle
    inner = slice(2, n - 2)  # skip the endpoints, which sit on the sites themselves
    i_min = int(np.argmin(clear[inner])) + 2
    fres = clear - 0.6 * f1
    j_min = int(np.argmin(fres[inner])) + 2
    min_clear = float(clear[i_min])
    min_fres = float(fres[j_min])
    status = "blocked" if min_clear < 0 else ("marginal" if min_fres < 0 else "clear")
    brg_ab = bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"])
    brg_ba = (brg_ab + 180) % 360
    step = max(1, n // 200)
    mi = d1 / 1609.344
    return {
        "a": a["id"], "b": b["id"], "dist_mi": round(d_m / 1609.344, 2),
        "status": status, "min_clear_ft": round(min_clear, 1),
        "min_clear_at_mi": round(float(mi[i_min]), 2),
        "fresnel60_margin_ft": round(min_fres, 1),
        "bearing_ab": round(brg_ab), "bearing_ba": round(brg_ba),
        "window_a": window_check(a, brg_ab), "window_b": window_check(b, brg_ba),
        "profile": {
            "mi": [round(float(v), 3) for v in mi[::step]],
            "ground": [round(float(v), 1) for v in ground[::step]],
            "obstacle": [round(float(v), 1) for v in obstacle[::step]],
            "ray": [round(float(v), 1) for v in ray[::step]],
            "fres60": [round(float(v), 1) for v in (ray - 0.6 * f1)[::step]],
        },
    }


def box_blur(z: np.ndarray, passes: int = 3) -> np.ndarray:
    out = z.copy()
    for _ in range(passes):
        p = np.pad(out, 1, mode="edge")
        out = np.asarray(sum(p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx]
                             for dy in (-1, 0, 1) for dx in (-1, 0, 1))) / 9
    return out


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def overlay_png(dem: Dem, lo: float, hi: float) -> bytes:
    z = dem.z
    ramp = np.array([hex_rgb(c) for c in RAMP], float)
    u = np.clip((z - lo) / (hi - lo), 0, 1) * (len(RAMP) - 1)
    i0 = np.floor(u).astype(int)
    i1 = np.minimum(i0 + 1, len(RAMP) - 1)
    f = (u - i0)[..., None]
    rgb = ramp[i0] * (1 - f) + ramp[i1] * f
    # Hillshade, sun from the NW at 45 deg; pixel size in feet.
    lat_mid = math.radians((dem.n + dem.s) / 2)
    px_x = (dem.e - dem.w) / dem.cols * 111_320 * math.cos(lat_mid) * M_TO_FT
    px_y = (dem.n - dem.s) / dem.rows * 110_540 * M_TO_FT
    gy, gx = np.gradient(box_blur(z, 1), px_y, px_x)
    slope = np.arctan(np.hypot(gx, gy) * 2.0)  # 2x vertical exaggeration
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = np.clip(shade, 0, 1)
    rgb = rgb * np.clip(0.9 + 0.6 * (shade - shade.mean()), 0.6, 1.08)[..., None]
    img = np.clip(rgb, 0, 255).astype(np.uint8)
    alpha = np.full(z.shape, 200, np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.dstack([img, alpha]), "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def contours_geojson(dem: Dem, interval: int = 10, index: int = 50) -> dict:
    zs = box_blur(dem.z, 4)
    lons = dem.w + (np.arange(dem.cols) + 0.5) * dem.sx
    lats = dem.n - (np.arange(dem.rows) + 0.5) * dem.sy
    levels = np.arange(math.ceil(zs.min() / interval) * interval, zs.max(), interval)
    fig, ax = plt.subplots()
    cs = ax.contour(lons, lats, zs, levels=levels)
    feats = []
    for lev, segs in zip(cs.levels, cs.allsegs, strict=True):
        for seg in segs:
            if len(seg) < 8:
                continue
            coords = [[round(float(x), 6), round(float(y), 6)] for x, y in seg[::2]]
            feats.append({"type": "Feature",
                          "properties": {"ft": int(lev), "index": int(lev) % index == 0},
                          "geometry": {"type": "LineString", "coordinates": coords}})
    plt.close(fig)
    return {"type": "FeatureCollection", "features": feats}


def best_paths(sites: list[dict], links: list[dict], root: str) -> dict:
    """Fewest-hop path from root over non-blocked links (marginal costs 1.5)."""
    cost = {"clear": 1.0, "marginal": 1.5}
    adj: dict[str, list[tuple[str, float]]] = {s["id"]: [] for s in sites}
    for lk in links:
        if lk["status"] in cost:
            adj[lk["a"]].append((lk["b"], cost[lk["status"]]))
            adj[lk["b"]].append((lk["a"], cost[lk["status"]]))
    dist = {root: 0.0}
    prev: dict[str, str] = {}
    todo = set(adj)
    while todo:
        u = min((n for n in todo if n in dist), key=lambda n: dist[n], default=None)
        if u is None:
            break
        todo.discard(u)
        for v, w in adj[u]:
            if dist[u] + w < dist.get(v, math.inf):
                dist[v] = dist[u] + w
                prev[v] = u
    paths = {}
    for s in sites:
        if s["id"] == root:
            continue
        if s["id"] not in dist:
            paths[s["id"]] = None
            continue
        p = [s["id"]]
        while p[-1] != root:
            p.append(prev[p[-1]])
        paths[s["id"]] = list(reversed(p))
    return paths


def profiles_png(sites: list[dict], links: list[dict], root: str, out: Path) -> None:
    by_id = {s["id"]: s for s in sites}
    mine = [lk for lk in links if root in (lk["a"], lk["b"])]
    mine.sort(key=lambda lk: lk["dist_mi"])
    cols = 3
    rows = math.ceil(len(mine) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(13, 3.3 * rows), squeeze=False)
    plt.rcParams["font.family"] = "Helvetica"
    lo = min(min(lk["profile"]["ground"]) for lk in mine) - 10
    hi = max(max(lk["profile"]["ray"]) for lk in mine) + 15
    for ax, lk in zip(axes.flat, mine, strict=False):
        p = lk["profile"]
        flip = lk["a"] != root
        mi = np.array(p["mi"])
        if flip:
            mi = lk["dist_mi"] - mi
        other = by_id[lk["b"] if lk["a"] == root else lk["a"]]
        ax.fill_between(mi, lo, p["obstacle"], color="#86b6ef", linewidth=0)
        ax.plot(mi, p["obstacle"], color="#184f95", linewidth=1.5)
        ax.plot(mi, p["ray"], color="#0b0b0b", linewidth=2)
        ax.plot(mi, p["fres60"], color="#898781", linewidth=1, linestyle=(0, (4, 3)))
        ax.set_ylim(lo, hi)
        ax.set_xlim(0, lk["dist_mi"])
        icon = {"clear": "OK", "marginal": "MARGINAL", "blocked": "BLOCKED"}[lk["status"]]
        ax.set_title(f"Home to {other['name']}  {lk['dist_mi']} mi\n"
                     f"{icon}: terrain {lk['min_clear_ft']:+.0f} ft at {lk['min_clear_at_mi']:.2f} mi",
                     fontsize=10, loc="left", color="#0b0b0b")
        ax.title.set_color(STATUS[lk["status"]] if lk["status"] == "blocked" else "#0b0b0b")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#c3c2b7")
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(colors="#898781", labelsize=8)
        ax.grid(axis="y", color="#e1e0d9", linewidth=0.6)
        ax.set_ylabel("ft above sea level", fontsize=8, color="#898781")
        ax.set_xlabel("miles from home", fontsize=8, color="#898781")
    for ax in list(axes.flat)[len(mine):]:
        ax.axis("off")
    fig.suptitle("Terrain between home and each friend (USGS bare earth, 4/3 earth). "
                 "Black = radio path, dashed = 60% Fresnel floor, blue = ground + curvature.",
                 fontsize=10, color="#0b0b0b", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out, dpi=130, facecolor="white")
    plt.close(fig)


def render_png(html: Path, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    # Use whichever headless shell is already installed, so a newer playwright
    # wheel does not demand a fresh browser download.
    shells = sorted(Path.home().glob("Library/Caches/ms-playwright/chromium_headless_shell-*/"
                                     "chrome-headless-shell-mac-arm64/chrome-headless-shell"))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=str(shells[-1]) if shells else None,
                              args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        pg = b.new_page(viewport={"width": 1500, "height": 1050}, device_scale_factor=2)
        pg.goto(html.as_uri() + "#print")
        pg.wait_for_function("window.__ready === true", timeout=90_000)
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(out))
        b.close()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cfg_path = Path(args[0]) if args else HERE / "sites.json"
    cfg = json.loads(cfg_path.read_text())
    out_dir = Path(cfg["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dem_path = HERE / "cache" / "dem.tif"
    if not dem_path.exists():
        fetch_dem(cfg["dem_bbox"], dem_path)
    dem = Dem(dem_path)

    sites = cfg["sites"]
    for s in sites:
        s["agl_ft"] = floor_to_agl_ft(s["floor"])
        s["ground_ft"] = round(float(dem.at(np.array([s["lat"]]), np.array([s["lon"]]))[0]), 1)
        s["top_ft"] = round(s["ground_ft"] + s["agl_ft"], 1)
    same = {frozenset(p) for p in cfg.get("same_building", [])}
    links = [link(dem, a, b) for a, b in itertools.combinations(sites, 2)
             if frozenset((a["id"], b["id"])) not in same]
    root = sites[0]["id"]
    paths = best_paths(sites, links, root)

    # Fit the color range to the sites' own ground: the river bottoms at the
    # grid edge would otherwise use up half the ramp. Lower ground clamps light.
    grounds = [s["ground_ft"] for s in sites]
    lo, hi = min(grounds) - 30, max(grounds) + 10
    lo, hi = math.floor(lo / 10) * 10, math.ceil(hi / 10) * 10
    overlay = base64.b64encode(overlay_png(dem, lo, hi)).decode()
    data = {"title": cfg["title"], "bbox": [dem.w, dem.s, dem.e, dem.n], "sites": sites,
            "links": links, "paths": paths, "root": root, "elev": [lo, hi],
            "ramp": RAMP, "status": STATUS, "default_profile": cfg.get("default_profile"), "contours": contours_geojson(dem)}
    html = (HERE / "map_template.html").read_text()
    html = html.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    html = html.replace("__OVERLAY__", overlay)
    html_path = out_dir / "map.html"
    html_path.write_text(html)
    table = [{k: v for k, v in lk.items() if k != "profile"} for lk in links]
    (out_dir / "links.json").write_text(json.dumps(
        {"sites": sites, "links": table, "paths": paths}, indent=1))
    profiles_png(sites, links, root, out_dir / "profiles.png")
    if "--no-png" not in sys.argv:
        render_png(html_path, out_dir / "map.png")
    for lk in sorted(table, key=lambda x: x["dist_mi"]):
        print(f"{lk['a']:>8} -> {lk['b']:<8} {lk['dist_mi']:5.2f} mi  {lk['status']:<8} "
              f"clear {lk['min_clear_ft']:+6.1f} ft @ {lk['min_clear_at_mi']:.2f}  "
              f"F60 {lk['fresnel60_margin_ft']:+6.1f}  win {lk['window_a']}/{lk['window_b']}")
    for s in sites:
        print(f"{s['id']:>8} ground {s['ground_ft']:6.1f}  +{s['agl_ft']:.0f}  top {s['top_ft']:6.1f}")
    print("paths from", root, json.dumps(paths))


if __name__ == "__main__":
    main()
