#!/usr/bin/env python3
"""Grade every roster in an ESPN draft room, from the Pick History tab.

Answers "is this roster good" with a number instead of an eyeball: each team is
scored on its optimal starting lineup using the same ESPN season projections the
VOR board is built from, so the grade and the drafting share one scale. The
output is a standings table of projected starter points, which is the quantity
this league's playoff seeding tiebreak (total points for) actually rewards.

Pick History is the right source: unlike the roster panel (abbreviated names, no
anchors) it carries every pick's FULL player name, so nothing falls out of the
grade on an ambiguous "J. Williams". All rows are read by textContent because
innerText is empty for anything ESPN has not laid out.
"""

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"
VOR = HERE / "vor.json"

FLEX = ("RB", "WR", "TE")

JS = """async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const tab = [...document.querySelectorAll('button')].find(
    (b) => (b.textContent || '').trim() === 'Pick History'
  );
  if (!tab) return { error: 'no Pick History tab' };
  tab.click();
  await wait(1200);
  const txt = (el) => ((el && el.textContent) || '').trim();
  const out = [];
  for (const row of document.querySelectorAll('.fixedDataTableRowLayout_rowWrapper')) {
    const a = row.querySelector('.player-news');
    if (!a) continue;
    const details = txt(row.querySelector('.player-details'));
    const cells = [...row.querySelectorAll('.public_fixedDataTableCell_cellContent')].map(txt);
    out.push({ pick: parseInt(cells[0], 10) || 0, name: txt(a), details, cells });
  }
  return out;
}"""


def send(js, wait=60):
    RESULT.unlink(missing_ok=True)
    CMD.write_text(
        json.dumps({"id": int(time.time() * 1000) % 100000, "op": "eval", "arg": js})
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.4)
    sys.exit("timeout talking to driver.py")


def norm(s):
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def team_of(cells, known_prefixes):
    """The fantasy-team cell is the one that is a team name, not a stat."""
    for c in cells:
        for t in known_prefixes:
            if c.startswith(t):
                return t
    return None


def lineup_points(players):
    """Optimal legal lineup: greedy on projection within slot requirements."""
    pool = sorted(players, key=lambda x: -x[1])
    used = set()
    total = 0.0
    for pos, n in {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "D/ST": 1, "K": 1}.items():
        got = 0
        for i, (p, pts) in enumerate(pool):
            if i in used or p != pos:
                continue
            used.add(i)
            total += pts
            got += 1
            if got == n:
                break
    for i, (p, pts) in enumerate(pool):  # FLEX
        if i not in used and p in FLEX:
            total += pts
            break
    return total


def read_picks():
    """Every pick in the room, deduplicated, each tagged with its fantasy team.

    Shared with the live ECR audit (`../examiner.py --live`), which needs the
    same board reconstruction: who was taken, by whom, in what order.
    """
    res = send(JS)
    if not res.get("ok"):
        sys.exit(f"driver error: {res.get('error')}")
    picks = res["data"]
    if isinstance(picks, dict):
        sys.exit(picks.get("error", "bad response"))

    # The fixed-data-table renders some rows twice (a pinned layer). A duplicated
    # RB would legally fill both RB slots and inflate that team's grade, so dedup
    # on the pick number, which is unique by construction.
    seen = set()
    picks = [
        p for p in picks if p["pick"] and not (p["pick"] in seen or seen.add(p["pick"]))
    ]

    # Team names come from the room itself: every cell that repeats across rows
    # and is not a player-details string is a fantasy team.
    from collections import Counter

    freq = Counter()
    for p in picks:
        for c in p["cells"]:
            if c and not c[0].isdigit() and c != p["details"]:
                freq[c] += 1
    teams = [t for t, n in freq.items() if n >= 3]
    for p in picks:
        p["team"] = team_of(p["cells"], teams)
    picks.sort(key=lambda p: p["pick"])
    return picks


def load_judge(which):
    """A judging board: {norm_name: (pos, points)}.

    'us' is the drafting board itself and can only measure execution.
    'consensus' is CBS + FFToday (sources the bot never drafts on), the fix
    for the self-grading loop: a rank that drops when the judge changes is a
    board problem, not a drafting problem.
    """
    if which == "us":
        data = json.loads(VOR.read_text())
        base = data["baseline"]
        return {
            k: (v["pos"], v["vor"] + base.get(v["pos"], 0.0))
            for k, v in data["players"].items()
        }
    con = HERE / "consensus.json"
    if not con.exists():
        sys.exit("no consensus.json; run fantasy/consensus.py first")
    return {
        k: (v["pos"], v["pts"]) for k, v in json.loads(con.read_text()).items()
    }


def standings(picks, proj):
    from collections import defaultdict

    rosters = defaultdict(list)
    named = defaultdict(list)
    missing = []
    for p in picks:
        team = p["team"]
        if not team:
            missing.append(f"no team cell: {p['cells']!r:.80}")
            continue
        key = norm(p["name"])
        if key in proj:
            rosters[team].append(proj[key])
            named[team].append((p["pick"], p["name"], *proj[key]))
        else:
            missing.append(f"{team}: {p['name']!r} not on this board")
    table = sorted(
        ((t, lineup_points(ps), len(ps)) for t, ps in rosters.items()),
        key=lambda x: -x[1],
    )
    return table, named, missing


def main():
    judges = ["us"]
    if "--judge" in sys.argv:
        arg = sys.argv[sys.argv.index("--judge") + 1]
        judges = ["us", "consensus"] if arg == "both" else [arg]

    picks = read_picks()
    print(f"picks read: {len(picks)}")

    ranks = {}
    for which in judges:
        table, named, missing = standings(picks, load_judge(which))
        print(f"\n== judged by: {which} ==")
        print(f"{'':>2} {'projected starters':>18}  team")
        for i, (name, pts, n) in enumerate(table, 1):
            tag = " <-- Chaos Legion" if "Chaos" in name else ""
            if "Chaos" in name:
                ranks[which] = i
            print(f"{i:>2} {pts:>18.1f}  {name} ({n} picks){tag}")

        # Comparing our build against the teams that beat us is the only way
        # the standings number turns into a lesson.
        if "--rosters" in sys.argv:
            top = int(sys.argv[sys.argv.index("--rosters") + 1])
            for name, pts, _ in table[:top]:
                print(f"\n{name}  ({pts:.1f})")
                for pick, who, pos, pp in sorted(named[name], key=lambda r: -r[3]):
                    print(f"  pk{pick:>4}  {pos:<5} {who:<24} {pp:>6.1f}")
        if missing:
            print("excluded from this judge's grades:")
            for m in missing:
                print("  " + m)

    if len(ranks) == 2:
        gap = ranks["consensus"] - ranks["us"]
        print(
            f"\nrank gap (consensus - us): {gap:+d}"
            "  [~0 = robust build; large positive = the board flatters us]"
        )


if __name__ == "__main__":
    main()
