"""season.js against the Python mix of the same outcome table, and the table
against the plain season run.

    python3 fantasy/scorebug/test_season.py              # build the table now (about 15 s)
    python3 fantasy/scorebug/test_season.py TABLE.json   # or test a saved one

Three checks, all of which must pass:

1. JS == Python: on random live win chances (some games decided, some open),
   season.js and the Python mix below agree to 1e-9 on every team and metric.
2. The positive control: mixed at the pregame chances, the cells give the
   plain run (`base`) back, within 1.5 points on every team and metric. The
   cells and the plain run are separate batches, so this is the check that
   the cell weights are right. It needs a fresh build: snapshot.py keeps the
   week's first `pre` in its cached table, and the plain run moves after it.
3. The negative control: mixed at one decided result (every home side wins),
   the odds move away from `base` by more than 1.5 points somewhere. Without
   it check 2 could pass on a mix that ignores the weights.

Node must be on PATH.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
METRICS = ("bye", "playoffs", "title", "seed1")
TOL_JS, TOL_BASE = 1e-9, 0.015


def mix(table: dict, p: list[float]) -> dict:
    out = {m: [0.0] * len(table["ids"]) for m in METRICS}
    for k, cell in enumerate(table["cells"]):
        w = 1.0
        for j, pj in enumerate(p):
            w *= pj if k >> j & 1 else 1 - pj
        for m in METRICS:
            for i, x in enumerate(cell[m]):
                out[m][i] += w * x / 10000
    return out


def js(table: dict, cases: list[list[float | None]]) -> list[dict]:
    script = f"""
import {{ seasonOdds }} from {json.dumps(str(HERE / 'season.js'))};
import {{ readFileSync }} from 'fs';
const {{ table, cases }} = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(p => seasonOdds(table, p))));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps({"table": table, "cases": cases}),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def build() -> dict:
    r = subprocess.run([sys.executable, str(FANTASY / "season_sim.py"), "--table", "--this-week"],
                       capture_output=True, text=True, check=True, cwd=FANTASY)
    return json.loads(r.stdout)


def main() -> int:
    table = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else build()
    rnd = random.Random(7)
    G = len(table["games"])
    pre = [x if x is not None else 0.5 for x in table.get("pre") or [None] * G]
    cases: list[list[float | None]] = [list(pre), [1.0] * G]
    for _ in range(20):
        cases.append([rnd.choice([0.0, 1.0, rnd.random(), None]) for _ in range(G)])
    got = js(table, cases)
    fails = []
    for c, g in zip(cases, got, strict=True):
        p = [x if x is not None else pre[j] for j, x in enumerate(c)]
        want = mix(table, p)
        for m in METRICS:
            for i, t in enumerate(g["teams"]):
                if abs(t[m] - want[m][i]) > TOL_JS:
                    fails.append(f"js {m} {t['name']}: {t[m]:.6f} vs {want[m][i]:.6f} at {c}")
    at_pre = mix(table, pre)
    worst = max((abs(at_pre[m][i] - table["base"][m][i] / 10000), m, table["names"][i])
                for m in METRICS for i in range(len(table["ids"])))
    print(f"positive control: largest gap between the mix at the pregame chances and the plain run "
          f"{worst[0]:.4f} ({worst[1]}, {worst[2]})")
    if worst[0] > TOL_BASE:
        fails.append(f"positive control: {worst[0]:.4f} > {TOL_BASE}")
    decided = mix(table, [1.0] * G)
    moved = max(abs(decided[m][i] - table["base"][m][i] / 10000) for m in METRICS for i in range(len(table["ids"])))
    print(f"negative control: every home side wins moves some team {moved:.4f}")
    if moved <= TOL_BASE:
        fails.append(f"negative control: a decided week moved nothing ({moved:.4f})")
    for f in fails[:10]:
        print("FAIL", f)
    print(f"{'PASS' if not fails else 'FAIL'}: {len(cases)} cases, {G} games, {len(table['ids'])} teams")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
