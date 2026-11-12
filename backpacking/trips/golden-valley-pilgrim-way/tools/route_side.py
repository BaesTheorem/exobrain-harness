"""Route detours on OSM footpaths with the FOSSGIS foot router. Writes src/side.json."""
import json, sys, time, urllib.request
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
legs = json.load(open(sys.argv[1]))
out = {}
for key, pts in legs.items():
    coords = ";".join(f"{lon},{lat}" for lat, lon in pts)
    url = f"https://routing.openstreetmap.de/routed-foot/route/v1/foot/{coords}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    r = d["routes"][0]
    out[key] = {"km": round(r["distance"] / 1000, 2), "line": r["geometry"]["coordinates"]}
    print(f"{key:28} {out[key]['km']:6.2f} km")
    time.sleep(1.5)
json.dump(out, open(sys.argv[2], "w"))
