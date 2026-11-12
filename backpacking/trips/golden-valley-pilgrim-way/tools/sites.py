"""Measure each site against the official GVPW 7-day line: km along route and km off route."""
import json, math, sys
R = json.load(open(sys.argv[1]))
line = R["line"]
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 12742 * math.asin(math.sqrt(h))
cum = [0.0]
for i in range(1, len(line)):
    cum.append(cum[-1] + hav(line[i-1], line[i]))
print(f"total {cum[-1]:.1f} km")
sites = json.load(open(sys.argv[2]))
out = []
for s in sites:
    p = [s["lon"], s["lat"]]
    best = min(range(len(line)), key=lambda i: hav(p, line[i]))
    # first pass over route may be later (route reuses Hereford leg); take min index within 50 m of min
    dmin = hav(p, line[best])
    idx = min(i for i in range(len(line)) if hav(p, line[i]) <= dmin + 0.05)
    s.update(km=round(cum[idx], 2), off_km=round(dmin, 2), idx=idx)
    out.append(s)
for s in sorted(out, key=lambda s: s["km"]):
    print(f'{s["km"]:6.1f}  off {s["off_km"]:4.2f}  {s["kind"]:10} {s["name"]}')
json.dump({"cum": cum, "sites": out}, open(sys.argv[3], "w"))
