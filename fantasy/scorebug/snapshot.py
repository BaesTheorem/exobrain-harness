"""Scorebug snapshot: the lineup model's inputs for every game this week.

The live part of the win probability is simple arithmetic once each starter's
mean, spread and pregame mixture are known: a started player is his live
points plus the share of his mean the clock has left, with the spread on the
square root of that share (espncli.value.row_moments). So the heavy model
(market blend, injury mixtures, fix rates, correlations) runs here, in
Python, and the scorebug Worker does the live arithmetic in the cloud. That
is what lets the app run with the Mac off.

    python3 fantasy/scorebug/snapshot.py            # print the snapshot JSON
    python3 fantasy/scorebug/snapshot.py --post     # send it, and the Wire analysis, to the Worker

`--post` reads the Worker URL and ingest token from scorebug.json (written
by fantasy/scorebug/deploy), or SCOREBUG_URL / SCOREBUG_TOKEN in the
environment (the GitHub Actions copy).

INVARIANTS
- Read-only against ESPN: it uses the `espn` client and never `espn-tx`.
- Every model number comes from espncli (row_mean, player_sd, row_moments,
  with_fallbacks, the corr table). `check` in each matchup is the Python
  win_prob at snapshot time, so the Worker can be tested against it.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
sys.path.insert(0, str(FANTASY))

from espncli.cli import games_remaining, matchup_view  # noqa: E402
from espncli.client import Espn  # noqa: E402
from espncli.value import (  # noqa: E402
    is_starter,
    load_corr,
    player_sd,
    row_mean,
    row_moments,
    with_fallbacks,
)
from ffmodel.corr import rho  # noqa: E402

SEASON = FANTASY / "draftbot" / "season_sim_latest.json"
CACHE = FANTASY / "dashboard" / "cache"
CONF = HERE / "scorebug.json"
ATHLETE = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def jerseys(ids: list[int]) -> dict[int, str | None]:
    """Jersey numbers from ESPN's public athlete API (the fantasy API has none),
    cached for a week per player. D/ST entries have negative ids and no number."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "jerseys.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    now = time.time()
    todo = [p for p in ids if p > 0 and not (cache.get(str(p)) and now - cache[str(p)]["at"] < 7 * 86400)]

    def one(pid: int) -> tuple[int, str | None]:
        try:
            req = urllib.request.Request(ATHLETE.format(pid), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return pid, json.load(r).get("athlete", {}).get("jersey")
        except Exception:  # noqa: BLE001 - a missing number is cosmetic
            return pid, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for pid, num in ex.map(one, todo):
            cache[str(pid)] = {"n": num, "at": now}
    if todo:
        path.write_text(json.dumps(cache))
    return {p: (cache.get(str(p)) or {}).get("n") for p in ids}


def side(rows: list[dict], fallback_rows: list[dict]) -> list[dict]:
    """Starters with what the live arithmetic needs. `pre` is the pregame
    (mean, sd), a mixture with the bench cover for a questionable or empty
    slot; `mean` and `sd` are the player's own, used once his game starts."""
    out = []
    fb = {id(r0): r1 for r0, r1 in zip(rows, fallback_rows, strict=True)}
    for r in rows:
        if not is_starter(r):
            continue
        mean = float(row_mean(r) or 0.0)
        pre = row_moments({**fb[id(r)], "actual": None}, {}, {})
        out.append({
            "id": r["id"], "slot": r["slot"], "name": r["name"], "pos": r["pos"], "team": r["team"],
            "opp": r["opp"], "kick": r["kick"], "kickoff": r["kickoff"].isoformat() if r.get("kickoff") else None, "status": r.get("status") or "",
            "proj": r.get("proj"), "mean": round(mean, 3), "sd": round(player_sd(r["pos"], mean), 3),
            "pre": [round(pre[0], 3), round(pre[1], 3)],
        })
    return out


def pack(me_rows: list[dict], opp_rows: list[dict], rate: float, corr: dict) -> dict:
    """Both sides' starters plus the nonzero correlations, as index pairs
    into me + opp. `rate` is the rival's fix rate (espncli.value.fix_rate)."""
    me = side(me_rows, with_fallbacks(me_rows))
    opp = side(opp_rows, with_fallbacks(opp_rows, rate, holes=True))
    both = me + opp
    pairs = []
    for i in range(len(both)):
        for j in range(i + 1, len(both)):
            v = rho(both[i], both[j], corr)
            if v:
                pairs.append([i, j, round(v, 4)])
    return {"me": me, "opp": opp, "pairs": pairs}


def matchup(api: Espn, week: int, data: dict, team_id: int, corr: dict, rem: dict) -> dict | None:
    m = matchup_view(api, week, data, team_id)
    if not m or not m.get("opp"):
        return None
    rate = (m.get("opp_fix") or {}).get("rate", 1.0)
    p = pack(m["me"]["rows"], m["opp"]["rows"], rate, corr)
    return {"id": m["matchup_id"],
            "me": {"team_id": m["me"]["team_id"], "team": m["me"]["team"], "rows": p["me"]},
            "opp": {"team_id": m["opp"]["team_id"], "team": m["opp"]["team"], "rows": p["opp"]},
            "pairs": p["pairs"], "check": {"frac": rem, "win": m.get("win")}}


def build() -> dict:
    api = Espn()
    week = api.current_week(api.league("mStatus"))
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", period=week)
    mine = api.resolve_team(data, None)["id"]
    corr = load_corr()
    rem = games_remaining(api, week)
    games = [m for m in data.get("schedule", []) if m.get("matchupPeriodId") == week and m.get("away")]

    def one(g: dict) -> dict | None:
        ids = (g["home"]["teamId"], g["away"]["teamId"])
        return matchup(api, week, data, mine if mine in ids else ids[0], corr, rem)

    # The first game runs alone: it fills espncli's file caches, which the
    # client writes through one temp name, so a cold cache (a fresh cloud
    # runner) raced when six threads filled it at once.
    first = one(games[0]) if games else None
    with ThreadPoolExecutor(max_workers=6) as ex:
        views = [v for v in [first, *ex.map(one, games[1:])] if v]
    nums = jerseys([r["id"] for v in views for k in ("me", "opp") for r in v[k]["rows"]])
    for v in views:
        for k in ("me", "opp"):
            for r in v[k]["rows"]:
                r["jersey"] = nums.get(r["id"])
    teams = {t["id"]: {"name": (t.get("name") or "").strip(), "logo": t.get("logo") or ""} for t in data.get("teams", [])}
    return {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "source": os.environ.get("SCOREBUG_SOURCE", "mac"),
            "season": api.season, "week": week, "mine": next(v["id"] for v in views if mine in (v["me"]["team_id"], v["opp"]["team_id"])),
            "views": views, "teams": teams,
            "season_sim": json.loads(SEASON.read_text()) if SEASON.exists() else None}


def wire_analysis() -> dict | None:
    """The rival-scan build for the Wire tab (espncli.rivals, rebuilt at most
    hourly). The tab still shows every move without it, from the Worker's own
    reads, so a failure here only drops the analysis."""
    try:
        from espncli import rivals  # noqa: PLC0415 - the snapshot must not fail on the analysis

        return rivals.cached(Espn())
    except Exception as e:  # noqa: BLE001
        print(f"snapshot: wire analysis skipped ({e})", file=sys.stderr)
        return None


def post(snap: dict, route: str = "/ingest") -> dict:
    conf = json.loads(CONF.read_text()) if CONF.exists() else {}
    url = os.environ.get("SCOREBUG_URL") or conf["url"]
    token = os.environ.get("SCOREBUG_TOKEN") or conf["ingest_token"]
    req = urllib.request.Request(f"{url}{route}", data=json.dumps(snap, default=str).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "content-type": "application/json",
                                          "User-Agent": "scorebug-snapshot"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


if __name__ == "__main__":
    snap = build()
    if "--post" in sys.argv:
        print(json.dumps(post(snap)))
        wire = wire_analysis()
        if wire:
            print(json.dumps(post(wire, "/ingest/wire")))
    else:
        print(json.dumps(snap, indent=1))
