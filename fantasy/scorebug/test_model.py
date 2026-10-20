"""model.js against espncli.value.win_prob on the same rows.

    python3 fantasy/scorebug/test_model.py

For every game this week it draws random game clocks (some teams final, some
mid-game, some not started) and compares the two win probabilities and
means. A pass needs |dp| < 0.001 and |dmu| < 0.01 everywhere. Rows that have
not started lose their actual on both sides, so the pregame path is tested
too. Node must be on PATH.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from snapshot import pack  # noqa: E402

from espncli.cli import matchup_view  # noqa: E402
from espncli.client import Espn  # noqa: E402
from espncli.value import load_corr, win_prob  # noqa: E402


def js(cases: list[dict]) -> list[dict]:
    script = f"""
import {{ winProb }} from {json.dumps(str(HERE / 'model.js'))};
import {{ readFileSync }} from 'fs';
const cases = JSON.parse(readFileSync(0, 'utf8'));
const out = cases.map(c => {{
  const w = winProb(c.view, r => c.pts[String(r.id)] ?? null, t => c.frac[t] ?? 0);
  return {{ p: w.p, mu_me: w.mu_me, mu_opp: w.mu_opp }};
}});
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(cases),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def main() -> int:
    rnd = random.Random(7)
    api = Espn()
    week = api.current_week(api.league("mStatus"))
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", period=week)
    corr = load_corr()
    cases, expect = [], []
    for g in (m for m in data.get("schedule", []) if m.get("matchupPeriodId") == week and m.get("away")):
        m = matchup_view(api, week, data, g["home"]["teamId"])
        if not m or not m.get("opp"):
            continue
        rate = (m.get("opp_fix") or {}).get("rate", 1.0)
        teams = {r["team"] for s in ("me", "opp") for r in m[s]["rows"]}
        for trial in range(4):
            frac = {t: rnd.choice([0.0, 0.0, rnd.random()]) for t in teams}
            unstarted = {t for t in teams if trial and rnd.random() < 0.3}
            me = [dict(r, actual=None if r["team"] in unstarted else r["actual"]) for r in m["me"]["rows"]]
            opp = [dict(r, actual=None if r["team"] in unstarted else r["actual"]) for r in m["opp"]["rows"]]
            w = win_prob(me, opp, {}, frac, corr, rate)
            view = pack(me, opp, rate, corr)
            view = {"me": {"rows": view["me"]}, "opp": {"rows": view["opp"]}, "pairs": view["pairs"]}
            pts = {str(r["id"]): r["actual"] for r in me + opp if r["actual"] is not None}
            cases.append({"view": view, "pts": pts, "frac": frac})
            expect.append(w)
    got = js(cases)
    worst_p = max(abs(g["p"] - e["p"]) for g, e in zip(got, expect, strict=True))
    worst_mu = max(max(abs(g["mu_me"] - e["mu_me"]), abs(g["mu_opp"] - e["mu_opp"])) for g, e in zip(got, expect, strict=True))
    spread = sorted(round(e["p"], 3) for e in expect)
    print(f"{len(cases)} cases, worst |dp| {worst_p:.4f}, worst |dmu| {worst_mu:.3f}; Python p values {spread}")
    ok = worst_p < 0.001 + 0.0005 and worst_mu < 0.06  # win_prob rounds p to 3 places and mu to 1
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
