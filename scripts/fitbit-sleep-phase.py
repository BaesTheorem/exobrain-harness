"""Estimate circadian phase from Fitbit main-sleep logs (MCP dump files)."""
import json, sys, statistics as st
from datetime import datetime, timedelta
from collections import defaultdict

rows = {}
for p in sys.argv[1:]:
    for s in json.load(open(p)).get("sleep", []):
        if not s.get("isMainSleep"):
            continue
        start = datetime.fromisoformat(s["startTime"][:19])
        end = datetime.fromisoformat(s["endTime"][:19])
        asleep = s.get("minutesAsleep", 0)
        if asleep < 180:
            continue
        onset = start + timedelta(minutes=s.get("minutesToFallAsleep", 0))
        # first non-wake epoch is a better onset when stage data exist
        lv = s.get("levels", {}).get("data", [])
        for e in lv:
            if e["level"] not in ("wake", "awake"):
                onset = datetime.fromisoformat(e["dateTime"][:19]); break
        rows[s["dateOfSleep"]] = (onset, end, asleep)

def clock(dt, ref):  # hours since midnight of ref night (wake date - 1), can exceed 24
    return (dt - datetime.combine(ref.date() - timedelta(days=1), datetime.min.time())).total_seconds() / 3600
def fmt(h):
    h %= 24; return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"

recs = []
for d, (on, end, asl) in sorted(rows.items()):
    wake = datetime.fromisoformat(d)
    o, w = clock(on, wake), clock(end, wake)
    recs.append(dict(date=d, dow=wake.weekday(), onset=o, wake=w, mid=(o + w) / 2, dur=asl / 60))

print(f"nights: {len(recs)}  range {recs[0]['date']} .. {recs[-1]['date']}")
def summ(label, rs):
    if len(rs) < 3: return
    on = [r["onset"] for r in rs]; wk = [r["wake"] for r in rs]; md = [r["mid"] for r in rs]; du = [r["dur"] for r in rs]
    print(f"{label:<22} n={len(rs):3d} onset {fmt(st.median(on))} wake {fmt(st.median(wk))} mid {fmt(st.median(md))} "
          f"(SD {st.pstdev(md)*60:.0f} min) sleep {st.median(du):.1f} h")
summ("ALL", recs)
summ("work-night (Su-Th)", [r for r in recs if r["dow"] in (0, 1, 2, 3, 4)])
summ("free-night (Fr,Sa)", [r for r in recs if r["dow"] in (5, 6)])
bym = defaultdict(list)
for r in recs: bym[r["date"][:7]].append(r)
for m in sorted(bym): summ(m, bym[m])
# chronotype MSFsc (Roenneberg): MSF - (SDf - SDweek)/2 if SDf > SDweek
free = [r for r in recs if r["dow"] in (5, 6)]; work = [r for r in recs if r["dow"] not in (5, 6)]
msf = st.median([r["mid"] for r in free]); sdf = st.median([r["dur"] for r in free]); sdw = st.median([r["dur"] for r in work])
sdweek = (5 * sdw + 2 * sdf) / 7
msfsc = msf - (sdf - sdweek) / 2 if sdf > sdweek else msf
print(f"MSF {fmt(msf)}  MSFsc {fmt(msfsc)}  social jetlag {abs(msf - st.median([r['mid'] for r in work]))*60:.0f} min")
on_all = st.median([r["onset"] for r in recs])
print(f"est DLMO (onset-2h): {fmt(on_all - 2)}   est CBTmin (DLMO+7h): {fmt(on_all + 5)}")
# recent 90 nights
rec90 = recs[-90:]; summ("last 90 logged", rec90)
o90 = st.median([r["onset"] for r in rec90]); print(f"last-90 est DLMO {fmt(o90-2)}  CBTmin {fmt(o90+5)}  melatonin 0.5mg at {fmt(o90-5)}")
# percent nights waking before CBTmin
print("nights waking before est CBTmin+1h (all):", sum(r["wake"] < on_all + 6 for r in recs), "/", len(recs))
