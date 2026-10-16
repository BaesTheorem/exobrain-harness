#!/usr/bin/env python3
"""Standings after every played week, rebuilt from the league schedule.

Reads mMatchup + mTeam through `bin/ff raw`, replays each decided week, and
ranks the table the way ESPN does: win percentage, then points for. A team on
its idle week keeps its record and its points (the idle week's score never
counts). `--html PATH` also writes an interactive bump chart.

INVARIANTS
- Read-only: it only calls `ff raw`.
- The last week's order must match `ff standings`; `--check` exits 1 if not.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MY_TEAM_ID = 12


def load_league() -> dict:
    out = subprocess.run(
        [str(HERE / "bin" / "ff"), "raw", "--views", "mMatchup,mTeam,mSettings", "--limit", "0"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def history(league: dict) -> dict:
    teams = {t["id"]: t["name"].strip() for t in league["teams"]}
    rec = {tid: {"w": 0, "l": 0, "t": 0, "pf": 0.0} for tid in teams}
    weeks = []
    by_week: dict[int, list] = {}
    for g in league["schedule"]:
        by_week.setdefault(g["matchupPeriodId"], []).append(g)
    for wk in sorted(by_week):
        games = [g for g in by_week[wk] if "away" in g]
        if not games or any(g["winner"] == "UNDECIDED" for g in games):
            break
        idle = [g["home"]["teamId"] for g in by_week[wk] if "away" not in g]
        results = {}
        for g in games:
            h, a = g["home"], g["away"]
            for side, other, won in ((h, a, "HOME"), (a, h, "AWAY")):
                r = rec[side["teamId"]]
                r["pf"] += side["totalPoints"]
                res = "T" if g["winner"] == "TIE" else ("W" if g["winner"] == won else "L")
                r[{"W": "w", "L": "l", "T": "t"}[res]] += 1
                results[side["teamId"]] = {
                    "result": res, "pts": side["totalPoints"],
                    "opp": teams[other["teamId"]], "opp_pts": other["totalPoints"],
                }

        def pct(r: dict) -> float:
            n = r["w"] + r["l"] + r["t"]
            return (r["w"] + 0.5 * r["t"]) / n if n else 0.5

        order = sorted(teams, key=lambda t: (-pct(rec[t]), -rec[t]["pf"]))
        weeks.append({
            "week": wk,
            "idle": [teams[t] for t in idle],
            "table": [
                {"rank": i + 1, "team": teams[t], "id": t,
                 "record": f'{rec[t]["w"]}-{rec[t]["l"]}' + (f'-{rec[t]["t"]}' if rec[t]["t"] else ""),
                 "pf": round(rec[t]["pf"], 1), "idle": t in idle, "game": results.get(t)}
                for i, t in enumerate(order)
            ],
        })
    return {"league": league.get("settings", {}).get("name", ""), "me": teams[MY_TEAM_ID], "weeks": weeks}


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Standings by week</title>
<style>
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;
 --text-muted:#8a8984;--grid:#e6e5e1;--other:#c9c8c2;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--cut:#52514e}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
 --surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;--grid:#2e2e2c;
 --other:#4a4a46;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--cut:#c3c2b7}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface-1:#1a1a19;--text-primary:#f0efec;
 --text-secondary:#c3c2b7;--text-muted:#8f8e86;--grid:#2e2e2c;--other:#4a4a46;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--cut:#c3c2b7}
html,body{margin:0;background:var(--surface-1)}
.viz-root{background:var(--surface-1);color:var(--text-primary);font:14px/1.4 -apple-system,"SF Pro Text",Inter,system-ui,sans-serif;
 padding:28px 32px 24px;width:1040px;box-sizing:border-box}
h1{font-size:20px;font-weight:600;margin:0 0 4px}
.sub{color:var(--text-secondary);margin:0 0 18px}
.legend{display:flex;gap:20px;color:var(--text-secondary);font-size:13px;margin-bottom:6px;flex-wrap:wrap}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{display:inline-block;width:18px;height:3px;border-radius:2px}
svg text{font-family:inherit}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round;transition:opacity .12s}
.dot{stroke-width:2}
.team.dim{opacity:.18}
.lbl{font-size:12.5px;fill:var(--text-secondary)}
.lbl.hi{fill:var(--text-primary);font-weight:600}
.axis{font-size:12px;fill:var(--text-muted)}
.tip{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--grid);
 border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;white-space:nowrap}
.tip b{font-weight:600}.tip .m{color:var(--text-secondary)}
details{margin-top:14px;color:var(--text-secondary);font-size:12.5px}
table{border-collapse:collapse;margin-top:8px}td,th{padding:2px 10px;text-align:left;border-bottom:1px solid var(--grid)}
@media (prefers-reduced-motion:reduce){.line{transition:none}}
</style></head>
<body><div class="viz-root">
<h1>__TITLE__</h1>
<p class="sub">Standings position after each week. Order is win percentage, then points for, the same as ESPN. Open circles mark a team's idle week.</p>
<div class="legend">__LEGEND__</div>
<svg id="c" width="976" height="520" role="img" aria-label="Bump chart of league standings by week"></svg>
<div class="tip" id="tip"></div>
<details><summary>Table view</summary><div id="tbl"></div></details>
</div>
<script>
const D = __DATA__;
const HI = __HI__;
const W=976,H=520,L=210,R=250,T=26,B=34;
const weeks=D.weeks.map(w=>w.week), n=D.weeks[0].table.length;
const x=i=>L+(weeks.length===1?0:i*(W-L-R)/(weeks.length-1));
const y=r=>T+(r-1)*(H-T-B)/(n-1);
const svg=document.getElementById('c'), NS='http://www.w3.org/2000/svg';
const el=(t,a,p=svg)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);p.appendChild(e);return e};
// grid + cutlines
weeks.forEach((w,i)=>{el('line',{x1:x(i),x2:x(i),y1:T-10,y2:H-B+8,stroke:'var(--grid)'});
 el('text',{x:x(i),y:H-8,'text-anchor':'middle',class:'axis'}).textContent='Week '+w});
[[2.5,'Bye line (top 2)'],[6.5,'Playoff line (top 6)']].forEach(([r,t])=>{
 el('line',{x1:L-8,x2:W-R+8,y1:y(r),y2:y(r),stroke:'var(--cut)','stroke-dasharray':'3 4','stroke-width':1,opacity:.55});
 el('text',{x:W-R+14,y:y(r)+4,class:'axis'}).textContent=t});
// series
const teams=D.weeks[0].table.map(r=>r.team);
const pos={};D.weeks.forEach((w,i)=>w.table.forEach(r=>{(pos[r.team]??=[])[i]=r}));
const color=t=>HI[t]||'var(--other)';
const order=[...teams].sort((a,b)=>(HI[a]?1:0)-(HI[b]?1:0)); // highlighted drawn last
const groups={};
order.forEach(t=>{
 const g=el('g',{class:'team','data-team':t}); groups[t]=g;
 const pts=pos[t].map((r,i)=>[x(i),y(r.rank)]);
 let d='M'+pts[0];for(let i=1;i<pts.length;i++){const mx=(pts[i-1][0]+pts[i][0])/2;d+=`C${mx},${pts[i-1][1]} ${mx},${pts[i][1]} ${pts[i][0]},${pts[i][1]}`}
 el('path',{d,class:'line',stroke:color(t),'stroke-width':HI[t]?3:2},g);
 pos[t].forEach((r,i)=>el('circle',{cx:x(i),cy:y(r.rank),r:HI[t]?5.5:4.5,class:'dot',
   fill:r.idle?'var(--surface-1)':color(t),stroke:r.idle?color(t):'var(--surface-1)','stroke-width':2},g));
 const f=pos[t][0], z=pos[t][pos[t].length-1];
 el('text',{x:L-14,y:y(f.rank)+4,'text-anchor':'end',class:'lbl'+(HI[t]?' hi':'')},g).textContent=`${f.rank}  ${t}`;
 el('text',{x:x(weeks.length-1)+14,y:y(z.rank)+4,class:'lbl'+(HI[t]?' hi':'')},g).textContent=`${z.rank}  ${t}  ${z.record}`;
 // fat hit target
 el('path',{d,fill:'none',stroke:'transparent','stroke-width':16,style:'cursor:pointer'},g);
});
const tip=document.getElementById('tip');
svg.addEventListener('mousemove',ev=>{
 const g=ev.target.closest('.team'); if(!g){tip.style.display='none';Object.values(groups).forEach(e=>e.classList.remove('dim'));return}
 const t=g.dataset.team; Object.entries(groups).forEach(([k,e])=>e.classList.toggle('dim',k!==t));
 const b=svg.getBoundingClientRect(); let i=Math.round((ev.clientX-b.left-L)/((W-L-R)/(weeks.length-1)));
 i=Math.max(0,Math.min(weeks.length-1,i)); const r=pos[t][i], gm=r.game;
 tip.innerHTML=`<b>${t}</b> <span class="m">after week ${weeks[i]}</span><br>#${r.rank} &middot; ${r.record} &middot; ${r.pf} PF<br>`+
  (gm?`<span class="m">${gm.result} ${gm.pts.toFixed(1)} to ${gm.opp_pts.toFixed(1)} vs ${gm.opp}</span>`:'<span class="m">Idle week</span>');
 tip.style.display='block';tip.style.left=(ev.clientX+14)+'px';tip.style.top=(ev.clientY+14)+'px';
});
svg.addEventListener('mouseleave',()=>{tip.style.display='none';Object.values(groups).forEach(e=>e.classList.remove('dim'))});
// table view
let h='<table><tr><th>Team</th>'+weeks.map(w=>`<th>Wk ${w}</th>`).join('')+'</tr>';
teams.forEach(t=>h+=`<tr><td>${t}</td>`+pos[t].map(r=>`<td>${r.rank} (${r.record}${r.idle?', idle':''})</td>`).join('')+'</tr>');
document.getElementById('tbl').innerHTML=h+'</table>';
</script></body></html>
"""


def write_html(hist: dict, path: Path, highlight: list[str]) -> None:
    slots = ["var(--s1)", "var(--s2)", "var(--s3)"]
    hi = {t: slots[i] for i, t in enumerate(highlight[:3])}
    legend = "".join(f'<span><i style="background:{c}"></i>{t}</span>' for t, c in hi.items())
    legend += '<span><i style="background:var(--other)"></i>Other teams (hover to trace)</span>'
    title = f'{hist["league"] or "League"}: standings by week' if hist["league"] else "Standings by week"
    html = (HTML.replace("__DATA__", json.dumps(hist)).replace("__HI__", json.dumps(hi))
            .replace("__LEGEND__", legend).replace("__TITLE__", title))
    path.write_text(html)


def main() -> int:
    ap = argparse.ArgumentParser(description="Standings after every played week.")
    ap.add_argument("--json", action="store_true", help="print the full history as JSON")
    ap.add_argument("--html", type=Path, help="write an interactive bump chart here")
    ap.add_argument("--highlight", default="", help="comma-separated teams to color (max 3); default: ours plus the two nearest the top")
    ap.add_argument("--check", action="store_true", help="exit 1 if the last week's order disagrees with ff standings")
    args = ap.parse_args()

    hist = history(load_league())
    if not hist["weeks"]:
        print("no decided weeks yet", file=sys.stderr)
        return 1
    last = hist["weeks"][-1]["table"]
    if args.json:
        print(json.dumps(hist, indent=2))
    else:
        for w in hist["weeks"]:
            print(f'Week {w["week"]}: ' + ", ".join(f'{r["rank"]} {r["team"]} {r["record"]}' for r in w["table"]))
    if args.html:
        hl = [t.strip() for t in args.highlight.split(",") if t.strip()]
        if not hl:
            hl = [hist["me"]] + [r["team"] for r in last if r["team"] != hist["me"]][:2]
        write_html(hist, args.html, hl)
        print(f"wrote {args.html}", file=sys.stderr)
    if args.check:
        out = subprocess.run([str(HERE / "bin" / "ff"), "standings"], capture_output=True, text=True).stdout
        espn = [ln for ln in out.splitlines() if ln[:3].strip().isdigit()]
        ours = [r["team"] for r in last]
        bad = [(i + 1, ours[i]) for i, ln in enumerate(espn) if ours[i] not in ln]
        print("check: matches ff standings" if not bad else f"check: MISMATCH at {bad}", file=sys.stderr)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
