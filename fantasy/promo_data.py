#!/usr/bin/env python3
"""The facts behind a matchup promo video, as one JSON file.

Collects this week's head-to-head matchup for a promo render: both teams
(record, seed, points for and its rank, streak, logo), both lineups with
projections, the NFL games that have starters from both sides (venue, kickoff,
network, from ESPN's public scoreboard), the win probability from `espn
matchup`, and each team's bye odds after a win and after a loss (the
`season_sim.py --this-week --table` cells, weighted by every other game's
pregame odds). It also downloads the two fantasy team logos, because a
custom ESPN logo needs the league cookies.

    python3 fantasy/promo_data.py --out DIR/matchup.json --assets DIR

The output names leaguemates' teams, so write it into a gitignored folder
(the animation kit keeps it in `src/promo/data/`).

INVARIANTS
- Read-only against ESPN: it only calls `espn matchup`, `ff raw` and
  `season_sim.py`, plus public GETs for the scoreboard and the logos.
- Every number in the output comes from one of those calls; nothing is typed in.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def run_json(cmd: list[str]) -> Any:
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out[: out.rfind("}") + 1], strict=False)


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def bye_odds(table: dict, team_id: int) -> dict[str, float]:
    """P(bye) for one team when the week's first game goes each way.

    Cell bit j set means the first-listed team of game j wins. Every other game
    is weighted by its pregame odds (`pre`), so the result is the marginal over
    the rest of the week."""
    ids, pre, games = table["ids"], table["pre"], table["games"]
    j = next(k for k, g in enumerate(games) if team_id in g)
    home_is_team = games[j][0] == team_id
    sums = {True: [0.0, 0.0], False: [0.0, 0.0]}
    for key, cell in enumerate(table["cells"]):
        w = 1.0
        for g in range(len(games)):
            if g == j:
                continue
            p = pre[g] if pre[g] is not None else 0.5
            w *= p if key >> g & 1 else 1 - p
        team_won = bool(key >> j & 1) == home_is_team
        sums[team_won][0] += w * cell["bye"][ids.index(team_id)] / 10000
        sums[team_won][1] += w
    return {"win": round(sums[True][0] / sums[True][1], 3), "loss": round(sums[False][0] / sums[False][1], 3),
            "now": round(table["base"]["bye"][ids.index(team_id)] / 10000, 3)}


def nfl_games(season: int, week: int) -> dict[str, dict]:
    """Week N of the NFL keyed by each team's abbreviation."""
    sb = json.loads(get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
                        f"?seasontype=2&week={week}&dates={season}"))
    out: dict[str, dict] = {}
    for e in sb.get("events", []):
        c = e["competitions"][0]
        v = c.get("venue", {})
        side = {t["homeAway"]: t["team"]["abbreviation"] for t in c["competitors"]}
        g = {"home": side.get("home"), "away": side.get("away"), "date": e["date"],
             "venue": v.get("fullName"), "city": v.get("address", {}).get("city"),
             "country": v.get("address", {}).get("country"), "neutral": c.get("neutralSite", False),
             "network": next((n for b in c.get("broadcasts", []) for n in b.get("names", [])), None)}
        for abbr in side.values():
            out[abbr] = g
    return out


def lineup(side: dict) -> list[dict]:
    keep = ("slot", "id", "name", "pos", "team", "opp", "kickoff", "kick", "status", "proj", "market")
    return [{k: r.get(k) for k in keep} | {"proj": round(r.get("proj") or 0, 1)} for r in side["rows"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="The facts behind a matchup promo video, as one JSON file.")
    ap.add_argument("--out", required=True, help="path of the JSON file to write")
    ap.add_argument("--assets", help="folder for the two fantasy logos (skipped when absent)")
    args = ap.parse_args()

    mu = run_json([str(HERE / "bin" / "espn"), "matchup", "--json"])
    league = run_json([str(HERE / "bin" / "ff"), "raw", "--views", "mMatchup,mTeam,mSettings", "--limit", "0"])
    table = run_json([sys.executable, str(HERE / "season_sim.py"), "--this-week", "--table"])
    creds = json.loads((HERE / "espn-credentials.json").read_text())
    season, week = int(creds["season"]), int(mu["week"])

    teams = {t["id"]: t for t in league["teams"]}
    by_pf = sorted(teams, key=lambda i: -teams[i]["points"])
    order = sorted(teams, key=lambda i: (teams[i].get("playoffSeed") or 99))

    def team(tid: int, side: dict) -> dict:
        t, rec = teams[tid], teams[tid]["record"]["overall"]
        return {"id": tid, "name": t["name"].strip(), "abbrev": t.get("abbrev"), "logo": t.get("logo"),
                "wins": rec["wins"], "losses": rec["losses"], "seed": t.get("playoffSeed"),
                "pf": round(t["points"], 1), "pf_rank": by_pf.index(tid) + 1, "pa": round(rec["pointsAgainst"], 1),
                "streak": {"type": rec.get("streakType"), "len": rec.get("streakLength")},
                "projected": side["projected"], "lineup": lineup(side), "bye_odds": bye_odds(table, tid)}

    me, opp = team(mu["me"]["team_id"], mu["me"]), team(mu["opp"]["team_id"], mu["opp"])
    reg_weeks = league["settings"]["scheduleSettings"]["matchupPeriodCount"]
    meetings = [g["matchupPeriodId"] for g in league["schedule"]
                if {g.get("home", {}).get("teamId"), g.get("away", {}).get("teamId")} == {me["id"], opp["id"]}
                and g["matchupPeriodId"] <= reg_weeks]

    nfl = nfl_games(season, week)
    starters = [(s, r) for s in ("me", "opp") for r in (me if s == "me" else opp)["lineup"] if r["slot"] not in ("BE", "IR")]
    shared: dict[str, dict] = {}
    for s, r in starters:
        g = nfl.get(r["team"])
        if not g:
            continue
        key = f"{g['away']}@{g['home']}"
        shared.setdefault(key, {**g, "me": [], "opp": []})[s].append(r["name"])
    shared_games = [g for g in shared.values() if g["me"] and g["opp"]]
    shared_games.sort(key=lambda g: g["date"])
    first = min((r for _s, r in starters), key=lambda r: r["kickoff"] or "9")

    out = {
        "league": league["settings"]["name"], "season": season, "week": week, "built": datetime.now().isoformat(timespec="minutes"),
        "home": "me" if mu["me_is_home"] else "opp", "me": me, "opp": opp,
        "win": {"me": mu["win"]["p"], "opp": round(1 - mu["win"]["p"], 3), "proj_margin": mu["margin"]},
        "meetings": meetings, "regular_season_weeks": reg_weeks,
        "standings": [{"seed": teams[i].get("playoffSeed"), "name": teams[i]["name"].strip(), "abbrev": teams[i].get("abbrev"),
                       "wins": teams[i]["record"]["overall"]["wins"], "losses": teams[i]["record"]["overall"]["losses"],
                       "pf": round(teams[i]["points"], 1)} for i in order],
        "shared_games": shared_games,
        "first_kickoff": {"name": first["name"], "kickoff": first["kickoff"], "team": first["team"], "opp": first["opp"],
                          "network": (nfl.get(first["team"]) or {}).get("network")},
        "nfl": {abbr: {k: g[k] for k in ("home", "away", "date", "venue", "city", "network")} for abbr, g in nfl.items()},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"wrote {args.out}: week {week}, {me['name']} vs {opp['name']}, {len(shared_games)} shared NFL games")

    if args.assets:
        dest = Path(args.assets)
        dest.mkdir(parents=True, exist_ok=True)
        cookie = f"espn_s2={creds['espn_s2']}; SWID={creds['SWID']}"
        for side, t in (("me", me), ("opp", opp)):
            if not t["logo"]:
                continue
            ext = ".svg" if t["logo"].endswith(".svg") else ".img"
            data = get(t["logo"], {"Cookie": cookie, "User-Agent": BROWSER_UA} if "mystique" in t["logo"] else None)
            (dest / f"logo_{side}{ext}").write_bytes(data)
            print(f"logo {side}: {len(data)} bytes")


if __name__ == "__main__":
    main()
