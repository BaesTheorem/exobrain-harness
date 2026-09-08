#!/usr/bin/env python3
"""Turn the live draft's room log into the playbook's draft record (markdown).

Reads room_picks.jsonl (written by supervise.py from the room's Pick History
panel) and vor.json (the board), and prints: Chaos Legion's picks with the
board's view of each, every team ranked by board value and by ESPN projection,
and where the room's positional runs happened. Re-run any time; it is a pure
function of the two files.

    python3 recap.py [--team "Chaos Legion"] [--teams 13] [--rounds 16]
"""
import argparse
import collections
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent


def norm(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|iii|ii|iv)\b", "", s.lower()))


NFL = ("ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
       "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO",
       "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH")
TAGS = ("DTD", "SSPD", "IR", "Q", "O", "D", "P")


def parse(cells):
    """cells = [pick, 'Name[tag]PROPOS', team, 2025 pts, proj pts, espn rank].

    ESPN runs name, injury tag, pro team and position together with no
    separator, so this peels from the right against known lists instead of
    guessing where a name ends ("Kenneth Walker IIIKC", "RJ HarveyDENRB").
    """
    head, team = cells[1], cells[2].strip()
    pos = "?"
    for cand in ("D/ST", "WRCB", "QB", "RB", "WR", "TE", "K"):
        if head.endswith(cand):
            pos = "WR" if cand == "WRCB" else cand
            head = head[: -len(cand)]
            break
    pro = ""
    for abbr in sorted(NFL, key=len, reverse=True):
        if head.endswith(abbr):
            pro, head = abbr, head[: -len(abbr)]
            break
    name = head
    if pos != "D/ST":
        for tag in TAGS:
            stem = name[: -len(tag)]
            if name.endswith(tag) and stem and (not stem[-1].isupper() or stem.endswith((" II", " III", " IV"))):
                name = name[: -len(tag)]
                break

    def num(x):
        try:
            return float(x)
        except ValueError:
            return None

    return {"pick": int(cells[0]), "name": name, "pro": pro, "pos": pos, "team": team,
            "pts2025": num(cells[3]), "proj": num(cells[4]), "espn_rank": num(cells[5])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="Chaos Legion")
    ap.add_argument("--teams", type=int, default=13)
    ap.add_argument("--rounds", type=int, default=16)
    args = ap.parse_args()

    vor = json.load(open(HERE / "vor.json"))["players"]
    board = {norm(p["name"]): p for p in vor.values()}
    picks = [parse(json.loads(ln)["cells"]) for ln in open(HERE / "room_picks.jsonl")]
    picks.sort(key=lambda p: p["pick"])
    for p in picks:
        p["round"] = (p["pick"] - 1) // args.teams + 1
        p["slot"] = (p["pick"] - 1) % args.teams + 1
        b = board.get(norm(p["name"]))
        p["vor"] = b["vor"] if b else None
        p["adp"] = b.get("adp") if b else None
        p["bye"] = b.get("bye") if b else None

    mine = [p for p in picks if p["team"] == args.team]
    print(f"### {args.team}: {len(mine)} picks of {len(picks)} made\n")
    print("| Rd.slot | Pick | Player | Pos | Bye | Board VOR | ADP | ESPN rk |")
    print("|---|---|---|---|---|---|---|---|")
    for p in mine:
        print(f"| {p['round']}.{p['slot']:02d} | {p['pick']} | {p['name']} ({p['pro']}) | {p['pos']} "
              f"| {p['bye'] or '-'} | {p['vor'] if p['vor'] is not None else '-'} "
              f"| {p['adp'] or '-'} | {int(p['espn_rank']) if p['espn_rank'] else '-'} |")

    teams = collections.defaultdict(lambda: {"vor": 0.0, "proj": 0.0, "n": 0, "pos": collections.Counter()})
    for p in picks:
        t = teams[p["team"]]
        t["vor"] += p["vor"] or 0.0
        t["proj"] += p["proj"] or 0.0
        t["n"] += 1
        t["pos"][p["pos"]] += 1
    by_vor = sorted(teams, key=lambda k: -teams[k]["vor"])
    by_proj = sorted(teams, key=lambda k: -teams[k]["proj"])
    print("\n### Every team, by the board's value (self-graded; the consensus judge is separate)\n")
    print("| # | Team | Board VOR | ESPN proj | proj rank | QB/RB/WR/TE/DST/K |")
    print("|---|---|---|---|---|---|")
    for i, k in enumerate(by_vor, 1):
        t = teams[k]
        c = t["pos"]
        print(f"| {i} | {k} | {t['vor']:.0f} | {t['proj']:.0f} | {by_proj.index(k) + 1} "
              f"| {c['QB']}/{c['RB']}/{c['WR']}/{c['TE']}/{c['D/ST']}/{c['K']} |")

    print("\n### Positional runs by round (count of each position taken)\n")
    print("| Round | QB | RB | WR | TE | D/ST | K |")
    print("|---|---|---|---|---|---|---|")
    for r in range(1, args.rounds + 1):
        c = collections.Counter(p["pos"] for p in picks if p["round"] == r)
        if not c:
            break
        print(f"| {r} | {c['QB']} | {c['RB']} | {c['WR']} | {c['TE']} | {c['D/ST']} | {c['K']} |")

    firsts = {}
    for p in picks:
        firsts.setdefault(p["pos"], []).append(p["pick"])
    print("\n### When the scarce positions went\n")
    for pos in ("QB", "TE", "D/ST", "K"):
        ps = firsts.get(pos, [])
        if ps:
            print(f"- **{pos}**: picks {', '.join(map(str, ps[:12]))}{'...' if len(ps) > 12 else ''}")


if __name__ == "__main__":
    main()
