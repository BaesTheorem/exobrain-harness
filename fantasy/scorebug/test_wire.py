"""wire.js against espncli.league_log.normalize on the same ESPN rows.

    python3 fantasy/scorebug/test_wire.py

Fetches the league's raw activity feed, every week's mTransactions2 and the
pending rows once, runs the Python normalizer and the Worker's JavaScript
one on that same input, and compares the two results field by field. A pass
needs identical event and pending lists. Node must be on PATH.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from espncli import league_log  # noqa: E402
from espncli.client import Espn  # noqa: E402


def js(raw: dict, teams: list[int], me: int, starts: list[int]) -> dict:
    script = f"""
import {{ normalize }} from {json.dumps(str(HERE / 'wire.js'))};
import {{ readFileSync }} from 'fs';
const c = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(normalize(c.raw, c.teams, c.me, c.starts)));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(
        {"raw": raw, "teams": teams, "me": me, "starts": starts}), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def main() -> int:
    api = Espn()
    data = api.league("mTeam", "mStatus")
    week = api.current_week(data)
    teams = [t["id"] for t in data["teams"]]
    me = int(api.creds["team_id"])
    starts = league_log.week_starts(api)
    raw = league_log.fetch_raw(api, week)
    py = json.loads(json.dumps(league_log.normalize(raw, teams, me, starts)))
    jv = js(raw, teams, me, starts)
    bad = 0
    for key in ("events", "pending"):
        if len(py[key]) != len(jv[key]):
            print(f"FAIL {key}: python {len(py[key])} rows, js {len(jv[key])}")
            bad += 1
        for i, (a, b) in enumerate(zip(py[key], jv[key], strict=False)):
            if a != b:
                print(f"FAIL {key}[{i}]:\n  py {a}\n  js {b}")
                bad += 1
                if bad > 5:
                    return 1
    kinds = sorted({e["kind"] for e in py["events"]})
    print(("PASS" if not bad else "FAIL") + f": {len(py['events'])} events ({', '.join(kinds)}), "
          f"{len(py['pending'])} pending, {len(raw['topics'])} feed topics, {len(raw['transactions'])} tx rows")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
