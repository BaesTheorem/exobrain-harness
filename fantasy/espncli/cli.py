"""espn -- read-only ESPN fantasy + NFL CLI for "Roll for First Down" (LMAO).

Sibling of `ff`. `ff` answers "where do I sit / what is my roster / when is
the draft"; this tool covers the in-season week: the matchup and its
projected margin (the variance rule), the pre-kickoff lineup check, the
waiver wire, player cards and news, the league activity feed, the draft
recap, a team's schedule, the scoring table, the NFL slate with odds and
weather, the injury report, and D/ST and K streamers.

Every subcommand takes --json for other scripts and --fresh to bypass the
day-old caches. Strategy lives in the skill and the playbook note, not here:
  ~/.claude/skills/fantasy-football/SKILL.md
  ~/Exobrain/Areas/Adventure & Creativity/Fantasy Football/Fantasy Football Playbook.md

INVARIANTS:
- Read-only. See client.py. This tool surfaces numbers; Alex decides.
- No league member's name is ever printed. Owners render as initials.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from typing import Any

from espncli.client import (
    BENCH,
    IR,
    POS,
    SLOT,
    STARTER_SLOTS,
    TZ,
    Espn,
    EspnError,
    initials,
    local,
    norm,
    season_actual,
    season_proj,
    team_name,
    warn,
    week_actual,
    week_proj,
)
from espncli.statmap import stat_name

MARGIN_COINFLIP = 3.0  # inside this many projected points the matchup is a toss-up


# ---- formatting ---------------------------------------------------------

def pts(x: float | None, nd: int = 1) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def when(dt: datetime | None) -> str:
    return "-" if dt is None else dt.strftime("%a %-I:%M%p").replace("AM", "a").replace("PM", "p")


def now() -> datetime:
    return datetime.now(TZ)


def table(rows: list[dict], cols: list[tuple[str, str, int, str]], indent: str = "  ") -> None:
    """cols: (header, key, width, align) with align 'l' or 'r'. Values are
    rendered with str(); None shows as '-'."""
    def cell(v: Any, w: int, a: str) -> str:
        s = "-" if v is None else str(v)
        if len(s) > w:
            s = s[: max(w - 1, 1)] + "…"
        return s.rjust(w) if a == "r" else s.ljust(w)
    print(indent + " ".join(cell(h, w, a) for h, _, w, a in cols))
    for r in rows:
        print(indent + " ".join(cell(r.get(k), w, a) for _, k, w, a in cols))


def emit(args: argparse.Namespace, data: Any, render) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
    else:
        render(data)


STATUS_ABBR = {"ACTIVE": "", "QUESTIONABLE": "Q", "DOUBTFUL": "D", "OUT": "OUT",
               "INJURY_RESERVE": "IR", "DAY_TO_DAY": "DTD", "SUSPENSION": "SUSP"}


def short_status(status: str | None) -> str:
    return STATUS_ABBR.get(status or "", status or "")


def signed(x: float | None) -> str:
    return "-" if x is None else f"{x + 0.0:+.1f}".replace("+-", "-")


def strip_html(s: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# ---- shared builders ----------------------------------------------------

def week_for(api: Espn, args: argparse.Namespace, data: dict | None = None) -> int:
    if getattr(args, "week", None):
        return int(args.week)
    return api.current_week(data or api.league("mStatus"))


def entry_row(api: Espn, e: dict, week: int) -> dict:
    """One roster entry as a flat row: slot, player, NFL context, points."""
    ppe = e.get("playerPoolEntry") or {}
    p = ppe.get("player") or {}
    tid = p.get("proTeamId")
    kick = api.kickoff(tid, week)
    started = bool(kick and kick <= now())
    actual = week_actual(p, api.season, week) if started else None
    slot_id = int(e.get("lineupSlotId", -1))
    return {
        "slot": SLOT.get(slot_id, "?"),
        "slotId": slot_id,
        "id": p.get("id"),
        "name": p.get("fullName") or "?",
        "pos": POS.get(p.get("defaultPositionId") or 0, "?"),
        "team": api.pro(tid)["abbrev"],
        "opp": api.opponent(tid, week),
        "kickoff": kick,
        "kick": when(kick) + (" (locked)" if started else ""),
        "status": short_status(p.get("injuryStatus")),
        "proj": week_proj(p, api.season, week),
        "actual": actual,
        "season_proj": season_proj(p, api.season),
        "owned": (p.get("ownership") or {}).get("percentOwned"),
        "eligible": p.get("eligibleSlots") or [],
    }


def slot_order(r: dict) -> tuple:
    s = r["slotId"]
    return (0, STARTER_SLOTS.index(s)) if s in STARTER_SLOTS else (1 if s == BENCH else 2, 0)


def roster_rows(api: Espn, entries: list[dict], week: int) -> list[dict]:
    return sorted((entry_row(api, e, week) for e in entries), key=slot_order)


def side_entries(api: Espn, data: dict, side: dict) -> tuple[list[dict], str]:
    """A matchup side's lineup for the requested period, with its provenance.
    ESPN keys the 'current' roster to the scoringPeriodId in the request, so
    this is the real lineup for past and present weeks; only a future week
    falls back to the roster as it stands today."""
    for key, label in (("rosterForCurrentScoringPeriod", "lineup"),
                       ("rosterForMatchupPeriod", "lineup")):
        r = side.get(key) or {}
        if r.get("entries"):
            return r["entries"], label
    return api.roster_entries(data, side["teamId"]), "current roster"


def starters_proj(rows: list[dict]) -> float:
    return round(sum(r["proj"] or 0.0 for r in rows if r["slotId"] not in (BENCH, IR)), 1)


def starters_actual(rows: list[dict]) -> float | None:
    vals = [r["actual"] for r in rows if r["slotId"] not in (BENCH, IR) and r["actual"] is not None]
    return round(sum(vals), 1) if vals else None


def print_lineup(rows: list[dict], show_bench: bool = True) -> None:
    cols = [("SLOT", "slot", 5, "l"), ("PLAYER", "name", 24, "l"), ("POS", "pos", 4, "l"),
            ("TEAM", "team", 4, "l"), ("OPP", "opp", 5, "l"), ("KICKOFF", "kick", 19, "l"),
            ("ST", "status", 4, "l"), ("PROJ", "proj_s", 6, "r"), ("ACT", "actual_s", 6, "r")]
    for r in rows:
        r["proj_s"], r["actual_s"] = pts(r["proj"]), pts(r["actual"])
    starters = [r for r in rows if r["slotId"] not in (BENCH, IR)]
    table(starters, cols)
    if show_bench:
        bench = [r for r in rows if r["slotId"] == BENCH]
        ir = [r for r in rows if r["slotId"] == IR]
        if bench:
            print("  --- bench ---")
            table(bench, cols)
        if ir:
            print("  --- IR ---")
            table(ir, cols)


def find_matchup(data: dict, week: int, team_id: int) -> dict | None:
    for m in data.get("schedule", []):
        if m.get("matchupPeriodId") != week:
            continue
        sides = [m.get("home"), m.get("away")]
        if any(s and s.get("teamId") == team_id for s in sides):
            return m
    return None


def variance_line(margin: float) -> str:
    if margin >= MARGIN_COINFLIP:
        return "favorite: start the floor, not the ceiling"
    if margin <= -MARGIN_COINFLIP:
        return "underdog: start the boom/bust player, ceiling wins this"
    return "coin flip: pick on projection and matchup, not variance"


# ---- subcommands --------------------------------------------------------

def cmd_teams(api: Espn, args: argparse.Namespace) -> None:
    data = api.league("mTeam", "mSettings")
    members = {m["id"]: m for m in data.get("members", [])}
    mine = api.my_team_id(data)
    rows = []
    for t in data["teams"]:
        r = t.get("record", {}).get("overall", {})
        tc = t.get("transactionCounter") or {}
        rows.append({
            "id": t["id"], "team": team_name(t), "abbrev": t.get("abbrev"),
            "owner": initials(members.get((t.get("primaryOwner") or (t.get("owners") or [None])[0]))),
            "wins": r.get("wins", 0), "losses": r.get("losses", 0), "ties": r.get("ties", 0),
            "pf": r.get("pointsFor", 0.0), "pa": r.get("pointsAgainst", 0.0),
            "waiver": t.get("waiverRank"), "acq": tc.get("acquisitions", 0),
            "trades": tc.get("trades", 0), "proj_rank": t.get("currentProjectedRank"),
            "mine": t["id"] == mine,
        })
    rows.sort(key=lambda r: (-r["wins"], -r["pf"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["rec"] = f"{r['wins']}-{r['losses']}" + (f"-{r['ties']}" if r["ties"] else "")
        r["pf_s"], r["pa_s"] = pts(r["pf"]), pts(r["pa"])
        r["mark"] = "<- LMAO" if r["mine"] else ""

    def render(rows):
        print(f"{data['settings']['name']} -- {len(rows)} teams\n")
        table(rows, [("#", "rank", 2, "r"), ("ID", "id", 2, "r"), ("TEAM", "team", 26, "l"),
                     ("ABBR", "abbrev", 5, "l"), ("OWN", "owner", 4, "l"), ("W-L", "rec", 6, "l"),
                     ("PF", "pf_s", 7, "r"), ("PA", "pa_s", 7, "r"), ("WVR", "waiver", 3, "r"),
                     ("ACQ", "acq", 3, "r"), ("TRD", "trades", 3, "r"), ("PRJ", "proj_rank", 3, "r"),
                     ("", "mark", 7, "l")])
        print("\nWVR = waiver priority (1 claims first; resets weekly to inverse standings). "
              "PRJ = ESPN's projected finish.")
    emit(args, rows, render)


def cmd_team(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    data = api.league("mTeam", "mRoster", "mSettings", period=week)
    t = api.resolve_team(data, args.team)
    rows = roster_rows(api, api.roster_entries(data, t["id"]), week)
    out = {"team": team_name(t), "team_id": t["id"], "week": week,
           "projected": starters_proj(rows), "actual": starters_actual(rows), "roster": rows}

    def render(out):
        print(f"{out['team']} -- week {week}\n")
        if not rows:
            print("  (empty roster: the draft has not happened yet)")
            return
        print_lineup(rows)
        line = f"\n  starters projected {pts(out['projected'])}"
        if out["actual"] is not None:
            line += f", scored so far {pts(out['actual'])}"
        print(line)
    emit(args, out, render)


def matchup_view(api: Espn, week: int, data: dict, team_id: int) -> dict | None:
    m = find_matchup(data, week, team_id)
    if m is None:
        return None
    names = {t["id"]: team_name(t) for t in data["teams"]}
    sides = {}
    for key in ("home", "away"):
        s = m.get(key)
        if not s:
            continue
        entries, prov = side_entries(api, data, s)
        rows = roster_rows(api, entries, week)
        sides[key] = {
            "team_id": s["teamId"], "team": names.get(s["teamId"], f"Team {s['teamId']}"),
            "projected": starters_proj(rows), "actual": starters_actual(rows),
            "espn_total": s.get("totalPoints"), "espn_live_proj": s.get("totalProjectedPointsLive"),
            "source": prov, "rows": rows,
        }
    me_key = "home" if sides.get("home", {}).get("team_id") == team_id else "away"
    opp_key = "away" if me_key == "home" else "home"
    out = {"week": week, "matchup_id": m.get("id"), "winner": m.get("winner"),
           "playoff": m.get("playoffTierType"), "me_is_home": me_key == "home",
           "me": sides.get(me_key), "opp": sides.get(opp_key)}
    if out["opp"]:
        out["margin"] = round(out["me"]["projected"] - out["opp"]["projected"], 1)
        out["rule"] = variance_line(out["margin"])
    return out


def cmd_matchup(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", period=week)
    t = api.resolve_team(data, args.team)
    out = matchup_view(api, week, data, t["id"])
    if out is None:
        raise EspnError(f"No week {week} matchup found for {team_name(t)}.")

    def render(out):
        me, opp = out["me"], out["opp"]
        if opp is None:
            print(f"Week {week}: {me['team']} is idle (the odd team out). No opponent.")
            return
        for label, s in (("YOU" if s_is_me else "OPPONENT", s) for s_is_me, s in ((True, me), (False, opp))):
            print(f"{label}: {s['team']} -- week {week} ({s['source']})")
            if s["rows"]:
                print_lineup(s["rows"], show_bench=False)
            else:
                print("  (no lineup yet)")
            tail = f"  projected {pts(s['projected'])}"
            if s["actual"] is not None:
                tail += f"   scored {pts(s['actual'])}"
            if s["espn_live_proj"] is not None:
                tail += f"   ESPN live projection {pts(s['espn_live_proj'])}"
            print(tail + "\n")
        if me["projected"] == 0 and opp["projected"] == 0:
            print("No projections yet: both lineups are empty or ESPN has not published the week.")
        else:
            print(f"Projected margin: {out['margin']:+.1f}  ->  {out['rule']}")
        if out["winner"] in ("HOME", "AWAY"):
            won = (out["winner"] == "HOME") == out["me_is_home"]
            print(f"Final: {'WIN' if won else 'LOSS'} {pts(me['espn_total'])} to {pts(opp['espn_total'])}")
        elif out["winner"] == "TIE":
            print(f"Final: TIE {pts(me['espn_total'])} to {pts(opp['espn_total'])}")
    emit(args, out, render)


def cmd_scoreboard(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", period=week)
    names = {t["id"]: team_name(t) for t in data["teams"]}
    mine = api.my_team_id(data)
    games, idle = [], []
    for m in sorted(data.get("schedule", []), key=lambda m: m.get("id", 0)):
        if m.get("matchupPeriodId") != week:
            continue
        if not (m.get("home") and m.get("away")):
            s = m.get("home") or m.get("away")
            idle.append(names.get(s["teamId"], "?"))
            continue
        g = {"id": m.get("id"), "winner": m.get("winner"), "playoff": m.get("playoffTierType")}
        for key in ("home", "away"):
            s = m[key]
            entries, _ = side_entries(api, data, s)
            rows = roster_rows(api, entries, week)
            g[key] = {"team_id": s["teamId"], "team": names.get(s["teamId"], "?"),
                      "projected": starters_proj(rows), "espn_total": s.get("totalPoints"),
                      "live_proj": s.get("totalProjectedPointsLive"), "mine": s["teamId"] == mine}
        games.append(g)
    out = {"week": week, "matchups": games, "idle": idle}

    def render(out):
        print(f"{data['settings']['name']} -- week {week} scoreboard\n")
        for g in games:
            a, h = g["away"], g["home"]
            def side(s):
                mark = "*" if s["mine"] else " "
                score = pts(s["espn_total"]) if (s["espn_total"] or 0) > 0 else "  -  "
                return f"{mark}{s['team']:<24} proj {pts(s['projected']):>6}  pts {score:>6}"
            res = ""
            if g["winner"] == "HOME":
                res = "  <- home won"
            elif g["winner"] == "AWAY":
                res = "  <- away won"
            print(f"  {side(a)}")
            print(f"  {side(h)}{res}\n")
        if idle:
            print(f"  idle this week: {', '.join(idle)}")
        print("  * = Chaos Legion. proj = sum of starters' ESPN weekly projections.")
    emit(args, out, render)


def cmd_check(api: Espn, args: argparse.Namespace) -> None:
    """The pre-kickoff checklist the playbook asks for every week."""
    week = week_for(api, args)
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", period=week)
    t = api.resolve_team(data, args.team)
    rows = roster_rows(api, api.roster_entries(data, t["id"]), week)
    counts = {int(k): v for k, v in data["settings"]["rosterSettings"]["lineupSlotCounts"].items() if v}
    starters = [r for r in rows if r["slotId"] not in (BENCH, IR)]
    bench = [r for r in rows if r["slotId"] == BENCH]
    problems, nudges = [], []

    def usable(r: dict) -> bool:
        return r["opp"] != "BYE" and r["status"] not in ("OUT", "IR", "SUSP", "D")

    def best_bench_for(slot_id: int, exclude: int | None) -> dict | None:
        cands = [b for b in bench if slot_id in b["eligible"] and usable(b) and b["id"] != exclude]
        cands.sort(key=lambda b: -(b["proj"] or 0.0))
        return cands[0] if cands else None

    # empty slots
    for slot_id, n in counts.items():
        if slot_id in (BENCH, IR):
            continue
        have = [r for r in starters if r["slotId"] == slot_id]
        for _ in range(n - len(have)):
            b = best_bench_for(slot_id, None)
            problems.append({"kind": "EMPTY", "slot": SLOT.get(slot_id, "?"), "player": None,
                             "fix": f"move {b['name']} in (proj {pts(b['proj'])})" if b else "nobody eligible on the bench"})
    # inactive / bye / questionable starters
    for r in starters:
        st = r["status"]
        kind = None
        if r["opp"] == "BYE":
            kind = "BYE"
        elif st in ("OUT", "IR", "SUSP", "D"):
            kind = {"D": "DOUBTFUL", "SUSP": "SUSPENDED"}.get(st, st)
        elif st == "Q":
            kind = "QUESTIONABLE"
        if kind:
            b = best_bench_for(r["slotId"], r["id"])
            problems.append({"kind": kind, "slot": r["slot"], "player": r["name"],
                             "kick": r["kick"],
                             "fix": (f"swap in {b['name']} ({b['pos']}, proj {pts(b['proj'])})" if b
                                     else "no usable bench option for this slot")})
    # bench players out-projecting a starter they could replace
    for b in bench:
        if not usable(b) or b["proj"] is None:
            continue
        for r in starters:
            if r["slotId"] in b["eligible"] and r["proj"] is not None and b["proj"] > r["proj"] + 1.0:
                nudges.append({"bench": b["name"], "bench_proj": b["proj"], "starter": r["name"],
                               "slot": r["slot"], "starter_proj": r["proj"],
                               "gain": round(b["proj"] - r["proj"], 1)})
    nudges.sort(key=lambda n: -n["gain"])
    # lock order
    locks = sorted((r for r in starters if r["kickoff"]), key=lambda r: r["kickoff"])
    first_game = None
    for pt in api.pro_teams().values():
        for g in pt["games"].get(str(week), []):
            d = local(g.get("date"))
            if d and (first_game is None or d < first_game[0]):
                first_game = (d, f"{api.pro(g.get('awayProTeamId'))['abbrev']} @ {api.pro(g.get('homeProTeamId'))['abbrev']}")
    mv = matchup_view(api, week, data, t["id"])
    out = {"week": week, "team": team_name(t), "problems": problems, "nudges": nudges[:5],
           "first_kickoff": {"when": first_game[0], "game": first_game[1]} if first_game else None,
           "lock_order": [{"player": r["name"], "slot": r["slot"], "kickoff": r["kickoff"]} for r in locks],
           "margin": mv.get("margin") if mv else None, "rule": mv.get("rule") if mv else None,
           "opponent": (mv.get("opp") or {}).get("team") if mv else None}

    def render(out):
        print(f"{out['team']} -- week {week} lineup check\n")
        if not rows:
            print("  (empty roster: the draft has not happened yet)")
            return
        if first_game:
            print(f"  first kickoff of the week: {when(first_game[0])} CT ({first_game[1]})")
        if problems:
            print(f"\n  !! {len(problems)} problem(s):")
            for p in problems:
                who = p["player"] or "(empty)"
                print(f"     {p['kind']:<12} {p['slot']:<5} {who:<24} -> {p['fix']}")
        else:
            print("\n  OK  every starter is active, has a game, and every slot is filled")
        if nudges:
            print("\n  bench out-projects a starter (projection only; check the variance rule):")
            for n in nudges[:5]:
                print(f"     {n['bench']} ({pts(n['bench_proj'])}) over {n['starter']} at {n['slot']} "
                      f"({pts(n['starter_proj'])}), +{n['gain']}")
        if mv and mv.get("opp"):
            print(f"\n  matchup vs {mv['opp']['team']}: projected {pts(mv['me']['projected'])} to "
                  f"{pts(mv['opp']['projected'])}, margin {mv['margin']:+.1f} -> {mv['rule']}")
        elif mv:
            print("\n  idle week: no opponent, nothing to set")
        print("\n  starters lock in this order:")
        for r in locks:
            print(f"     {when(r['kickoff']):<12} {r['slot']:<5} {r['name']}")
        print("\n  Lineup Protection is OFF in this league. Fix problems before the slot's kickoff.")
    emit(args, out, render)


POOL_SLOT = {"QB": [0], "RB": [2], "WR": [4], "TE": [6], "K": [17], "DST": [16], "D/ST": [16],
             "FLEX": [23], "ALL": None}


def pool_rows(api: Espn, week: int, pos: str, limit: int, statuses: list[str]) -> list[dict]:
    slots = POOL_SLOT.get(pos.upper())
    if pos.upper() not in POOL_SLOT:
        raise EspnError(f"Unknown position '{pos}'. Use QB, RB, WR, TE, K, DST, FLEX, or ALL.")
    filt: dict[str, Any] = {
        "filterStatus": {"value": statuses},
        "limit": limit,
        "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
        "filterStatsForTopScoringPeriodIds": {
            "value": 2,
            "additionalValue": [f"00{api.season}", f"10{api.season}", f"00{api.season - 1}",
                                f"11{api.season}{week}", f"01{api.season}{week}"]},
    }
    if slots:
        filt["filterSlotIds"] = {"value": slots}
    rows = []
    for e in api.pool(filt, period=week):
        p = e.get("player") or {}
        own = p.get("ownership") or {}
        tid = p.get("proTeamId")
        rows.append({
            "id": p.get("id"), "name": p.get("fullName"), "pos": POS.get(p.get("defaultPositionId") or 0, "?"),
            "team": api.pro(tid)["abbrev"], "team_id": tid, "opp": api.opponent(tid, week),
            "avail": "WVR" if e.get("status") == "WAIVERS" else "FA",
            "status": short_status(p.get("injuryStatus")),
            "proj": week_proj(p, api.season, week), "season_proj": season_proj(p, api.season),
            "season_actual": season_actual(p, api.season),
            "last_season": season_actual(p, api.season - 1),
            "owned": own.get("percentOwned"), "trend": own.get("percentChange"),
            "started": own.get("percentStarted"), "adp": own.get("averageDraftPosition"),
        })
    return rows


def cmd_fa(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    pos = args.pos.upper()
    limit = 40 if pos in ("K", "DST", "D/ST") else (400 if pos == "ALL" else 150)
    statuses = ["WAIVERS"] if args.waivers else ["FREEAGENT", "WAIVERS"]
    rows = pool_rows(api, week, pos, limit, statuses)
    key = {"proj": lambda r: r["proj"] or -1, "season": lambda r: r["season_proj"] or -1,
           "owned": lambda r: r["owned"] or -1, "trend": lambda r: r["trend"] or -999,
           "points": lambda r: r["season_actual"] or -1}[args.sort]
    rows.sort(key=key, reverse=True)
    rows = rows[: args.n]

    def render(rows):
        print(f"Available {pos} -- week {week}, sorted by {args.sort}\n")
        for r in rows:
            r["proj_s"], r["sp_s"] = pts(r["proj"]), pts(r["season_proj"], 0)
            r["own_s"] = pts(r["owned"]); r["tr_s"] = signed(r["trend"])
            r["pts_s"] = pts(r["season_actual"]); r["adp_s"] = pts(r["adp"], 0)
        table(rows, [("PLAYER", "name", 24, "l"), ("POS", "pos", 4, "l"), ("TEAM", "team", 4, "l"),
                     ("OPP", "opp", 5, "l"), ("AV", "avail", 3, "l"), ("ST", "status", 4, "l"),
                     ("PROJ", "proj_s", 6, "r"), ("SEAS", "sp_s", 5, "r"), ("PTS", "pts_s", 6, "r"),
                     ("%OWN", "own_s", 6, "r"), ("7D%", "tr_s", 6, "r"), ("ADP", "adp_s", 5, "r")])
        print("\nAV: FA = add now, WVR = on waivers (1-day period, reverse-standings priority). "
              "PROJ = this week, SEAS = season projection, PTS = season to date, 7D% = ownership change.")
    emit(args, rows, render)


def player_card(api: Espn, pid: int, week: int) -> dict:
    cards = api.player_cards([pid], period=week)
    if not cards:
        raise EspnError(f"ESPN returned no card for player {pid}.")
    e = cards[0]
    p = e["player"]
    tid = p.get("proTeamId")
    own = p.get("ownership") or {}
    weekly = []
    for wk in range(1, 19):
        pr, ac = week_proj(p, api.season, wk), week_actual(p, api.season, wk)
        if pr is None and ac is None:
            continue
        kick = api.kickoff(tid, wk)
        weekly.append({"week": wk, "opp": api.opponent(tid, wk), "proj": pr,
                       "actual": ac if (kick and kick <= now()) else None})
    return {
        "id": p.get("id"), "name": p.get("fullName"), "pos": POS.get(p.get("defaultPositionId") or 0, "?"),
        "team": api.pro(tid)["abbrev"], "team_name": api.pro(tid)["name"], "bye": api.pro(tid)["bye"],
        "jersey": p.get("jersey"), "status": p.get("injuryStatus"), "injured": p.get("injured"),
        "injury": p.get("injuryDetails"),
        "on_team_id": e.get("onTeamId"), "avail": e.get("status"),
        "owned": own.get("percentOwned"), "started": own.get("percentStarted"),
        "trend": own.get("percentChange"), "adp": own.get("averageDraftPosition"),
        "week": week, "opp": api.opponent(tid, week), "proj": week_proj(p, api.season, week),
        "season_proj": season_proj(p, api.season), "season_actual": season_actual(p, api.season),
        "last_season": season_actual(p, api.season - 1),
        "weekly": weekly,
    }


def player_news(api: Espn, pid: int, n: int) -> list[dict]:
    if n <= 0:
        return []
    try:
        d = api.public("fantasy/v2/games/ffl/news/players", playerId=pid, limit=n)
    except EspnError as e:
        warn(f"(news unavailable: {e})")
        return []
    return [{"published": f.get("published"), "headline": strip_html(f.get("headline")),
             "story": strip_html(f.get("story")), "type": f.get("type")} for f in d.get("feed", [])]


def cmd_player(api: Espn, args: argparse.Namespace) -> None:
    q = " ".join(args.name)
    week = week_for(api, args)
    hit = api.resolve_one(q)
    card = player_card(api, hit["id"], week)
    data = api.league("mTeam")
    names = {t["id"]: team_name(t) for t in data["teams"]}
    card["rostered_by"] = names.get(card["on_team_id"]) if card["on_team_id"] else None
    card["news"] = player_news(api, hit["id"], args.news)

    def render(c):
        where = c["rostered_by"] or {"FREEAGENT": "free agent", "WAIVERS": "on waivers"}.get(c["avail"], c["avail"])
        print(f"{c['name']}  {c['pos']}  {c['team']} ({c['team_name']}, bye {c['bye']})  #{c['jersey'] or '-'}")
        st = c["status"] or "ACTIVE"
        inj = c.get("injury") or {}
        if isinstance(inj, dict) and inj:
            st += f" ({inj.get('injury') or inj.get('type') or ''}".rstrip() + ")" if inj else ""
        print(f"  status      {st}")
        print(f"  in league   {where}")
        print(f"  ownership   {pts(c['owned'])}% rostered, {pts(c['started'])}% started, "
              f"7-day {signed(c['trend'])}, ADP {pts(c['adp'])}")
        print(f"  week {c['week']:<2}     {c['opp']:<5} projected {pts(c['proj'])}")
        print(f"  season      projected {pts(c['season_proj'])}, scored {pts(c['season_actual'])}, "
              f"last season {pts(c['last_season'])}")
        if c["weekly"]:
            print("\n  week  opp    proj   actual")
            for w in c["weekly"]:
                print(f"  {w['week']:>4}  {w['opp']:<5} {pts(w['proj']):>6} {pts(w['actual']):>8}")
        for item in c["news"]:
            d = (item["published"] or "")[:10]
            print(f"\n  [{d}] {item['headline']}")
            if args.long and item["story"] and item["story"] != item["headline"]:
                print("    " + item["story"])
    emit(args, card, render)


def cmd_news(api: Espn, args: argparse.Namespace) -> None:
    hit = api.resolve_one(" ".join(args.name))
    items = player_news(api, hit["id"], args.n)
    out = {"player": hit["name"], "id": hit["id"], "news": items}

    def render(out):
        print(f"{hit['name']} -- latest news\n")
        if not items:
            print("  (no news items)")
        for item in items:
            print(f"  [{(item['published'] or '')[:10]}] {item['headline']}")
            story = item["story"] or ""
            if story and story != item["headline"]:
                if not args.long and len(story) > 500:
                    story = story[:500].rsplit(" ", 1)[0] + " … (--long for the rest)"
                print("    " + story + "\n")
    emit(args, out, render)


ACTIVITY = {178: "ADD (free agent)", 180: "ADD (waiver)", 179: "DROP", 239: "DROP",
            181: "TRADE accepted", 244: "TRADE"}


def cmd_activity(api: Espn, args: argparse.Namespace) -> None:
    """League activity feed. Verified against the API shape only up to an
    empty feed (2026-09-07, pre-draft); the message field semantics follow
    the espn-api package. Re-check the first time real moves appear."""
    data = api.league("mTeam")
    names = {t["id"]: team_name(t) for t in data["teams"]}
    if args.pending:
        d = api.league("mPendingTransactions")
        txs = d.get("pendingTransactions") or d.get("transactions") or []
        ids = [it.get("playerId") for tx in txs for it in tx.get("items", [])]
        pnames = api.names_for([i for i in ids if i])
        out = [{"type": tx.get("type"), "status": tx.get("status"), "team": names.get(tx.get("teamId")),
                "week": tx.get("scoringPeriodId"), "process": local(tx.get("processDate")),
                "items": [{"action": it.get("type"), "player": pnames.get(it.get("playerId"), it.get("playerId")),
                           "from": names.get(it.get("fromTeamId")), "to": names.get(it.get("toTeamId"))}
                          for it in tx.get("items", [])]} for tx in txs]

        def render(out):
            print("Pending transactions\n")
            if not out:
                print("  (none)")
            for tx in out:
                print(f"  {tx['type']:<10} {tx['status'] or '':<10} {tx['team'] or '':<24} "
                      f"week {tx['week']}  processes {when(tx['process'])}")
                for it in tx["items"]:
                    print(f"      {it['action']:<5} {it['player']}")
        emit(args, out, render)
        return
    filt = {"topics": {"filterType": {"value": ["ACTIVITY_TRANSACTIONS"]}, "limit": args.n,
                       "limitPerMessageSet": {"value": 25}, "offset": 0,
                       "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                       "sortFor": {"sortPriority": 2, "sortAsc": False},
                       "filterIncludeMessageTypeIds": {"value": list(ACTIVITY)}}}
    d = api.league("kona_league_communication", path="/communication/", filt=filt)
    topics = d.get("topics", [])
    ids = [m.get("targetId") for t in topics for m in t.get("messages", [])]
    pnames = api.names_for([i for i in ids if i])
    out = []
    for t in topics:
        for m in t.get("messages", []):
            mt = m.get("messageTypeId")
            team = m.get("to") if mt in (178, 180) else m.get("from")
            out.append({"date": local(m.get("date") or t.get("date")), "type": mt,
                        "action": ACTIVITY.get(mt, f"type {mt}"),
                        "team": names.get(team, str(team)),
                        "player": pnames.get(m.get("targetId"), str(m.get("targetId"))),
                        "from": names.get(m.get("from")), "to": names.get(m.get("to"))})
    out.sort(key=lambda r: r["date"] or datetime.min.replace(tzinfo=TZ), reverse=True)

    def render(out):
        print("League activity\n")
        if not out:
            print("  (no transactions yet)")
        for r in out:
            d = r["date"].strftime("%m-%d %-I:%M%p") if r["date"] else "-"
            print(f"  {d:<13} {r['team']:<24} {r['action']:<18} {r['player']}")
    emit(args, out, render)


def cmd_draft(api: Espn, args: argparse.Namespace) -> None:
    data = api.league("mDraftDetail", "mTeam", "mSettings")
    ds = data["settings"].get("draftSettings", {})
    dd = data.get("draftDetail", {})
    names = {t["id"]: team_name(t) for t in data["teams"]}
    abbr = {t["id"]: t.get("abbrev") or "?" for t in data["teams"]}
    mine = api.my_team_id(data)
    picks = dd.get("picks", [])
    size = data["settings"].get("size", 0) or len(names)
    order = [p["teamId"] for p in picks[:size]] if picks else ds.get("pickOrder", [])
    # ESPN marks an unmade pick with playerId -1. D/STs have negative ids too
    # (-16001 and down), so "made" cannot mean "positive" (2026-09-07: that
    # filter hid every round-11 D/ST pick and reported 195/208).
    made = [p for p in picks if p.get("playerId") not in (None, 0, -1)]
    out: dict[str, Any] = {
        "date": local(ds.get("date")), "type": ds.get("type"), "clock": ds.get("timePerSelection"),
        "order_type": ds.get("orderType"),
        "status": "DONE" if dd.get("drafted") else ("IN PROGRESS" if dd.get("inProgress") else "not started"),
        "picks_made": len(made), "picks_total": len(picks),
        "order": [{"slot": i, "team_id": tid, "team": names.get(tid), "mine": tid == mine}
                  for i, tid in enumerate(order, 1)],
        "my_slot": next((i for i, tid in enumerate(order, 1) if tid == mine), None),
    }
    show_picks = args.picks or args.mine or args.team or bool(made)
    if show_picks and made:
        pnames = api.names_for([p["playerId"] for p in made])
        idx = {p["id"]: p for p in api.players_index()}
        rows = []
        for p in made:
            meta = idx.get(p["playerId"], {})
            tid = int(p.get("teamId") or 0)
            rows.append({"round": p.get("roundId"), "pick": p.get("roundPickNumber"),
                         "overall": p.get("overallPickNumber"), "team_id": tid,
                         "abbrev": abbr.get(tid), "team": names.get(tid),
                         "player": pnames.get(p["playerId"], str(p["playerId"])),
                         "pos": meta.get("pos") or ("D/ST" if p["playerId"] < 0 else "?"),
                         "nfl": api.pro(meta.get("team"))["abbrev"] if meta else "",
                         "auto": bool(p.get("autoDraftTypeId")), "keeper": p.get("keeper")})
        if args.mine:
            rows = [r for r in rows if r["team_id"] == mine]
        elif args.team:
            t = api.resolve_team(data, args.team)
            rows = [r for r in rows if r["team_id"] == t["id"]]
        out["picks"] = rows

    def render(out):
        print(f"{data['settings']['name']} -- draft\n")
        print(f"  date     {out['date'].strftime('%A %B %-d, %Y %-I:%M %p %Z') if out['date'] else 'NOT SCHEDULED'}")
        print(f"  type     {out['type']}, {out['clock']}s per pick, order {out['order_type']}")
        print(f"  status   {out['status']} ({out['picks_made']}/{out['picks_total']} picks made)")
        print("\n  order:")
        for o in out["order"]:
            print(f"    {o['slot']:>2}  {o['team']}{'  <- LMAO' if o['mine'] else ''}")
        if out["order_type"] == "DRAFT_START" and out["status"] == "not started":
            print("\n  DRAFT_START order: ESPN randomizes when the room opens, so the list above "
                  "is the placeholder, not the slot.")
        if out.get("picks"):
            print("\n  picks:")
            for r in out["picks"]:
                mark = " <-" if r["team_id"] == mine else ""
                auto = " (auto)" if r["auto"] else ""
                print(f"    {r['round']:>2}.{r['pick']:<2} #{r['overall']:<3} {r['abbrev']:<5} "
                      f"{r['player']:<24} {r['pos']:<4} {r['nfl']}{auto}{mark}")
    emit(args, out, render)


def cmd_schedule(api: Espn, args: argparse.Namespace) -> None:
    data = api.league("mTeam", "mMatchup", "mSettings")
    t = api.resolve_team(data, args.team)
    names = {x["id"]: team_name(x) for x in data["teams"]}
    cur = api.current_week(data)
    reg = data["settings"]["scheduleSettings"].get("matchupPeriodCount", 14)
    rows = []
    for m in sorted(data.get("schedule", []), key=lambda m: (m.get("matchupPeriodId", 0), m.get("id", 0))):
        home, away = m.get("home"), m.get("away")
        sides = [s for s in (home, away) if s]
        if not any(s["teamId"] == t["id"] for s in sides):
            continue
        wk = m.get("matchupPeriodId")
        if len(sides) == 1:
            rows.append({"week": wk, "opp": "idle", "result": "", "score": "", "playoff": m.get("playoffTierType")})
            continue
        me = home if home["teamId"] == t["id"] else away
        opp = away if me is home else home
        res = ""
        if m.get("winner") == "HOME":
            res = "W" if me is home else "L"
        elif m.get("winner") == "AWAY":
            res = "W" if me is away else "L"
        elif m.get("winner") == "TIE":
            res = "T"
        score = f"{pts(me.get('totalPoints'))} - {pts(opp.get('totalPoints'))}" if res else ""
        rows.append({"week": wk, "opp": names.get(opp["teamId"], "?"), "home": me is home,
                     "result": res, "score": score, "playoff": m.get("playoffTierType")})

    def render(rows):
        print(f"{team_name(t)} -- {api.season} schedule\n")
        for r in rows:
            tag = ""
            if r["week"] == cur:
                tag = "  <- this week"
            elif r["week"] and r["week"] > reg and r["playoff"] not in (None, "NONE"):
                tag = f"  [{r['playoff'].lower()}]"
            vs = "" if r["opp"] == "idle" else ("vs " if r.get("home") else "at ")
            print(f"  week {r['week']:>2}  {vs}{r['opp']:<26} {r['result']:<2} {r['score']}{tag}")
        print(f"\n  regular season {reg} weeks, playoffs after. `ff schedule` shows every team's idle week.")
    emit(args, rows, render)


def cmd_settings(api: Espn, args: argparse.Namespace) -> None:
    data = api.league("mSettings")
    s = data["settings"]
    sc, rs, aq, ss, ts, ds = (s["scoringSettings"], s["rosterSettings"], s["acquisitionSettings"],
                              s["scheduleSettings"], s.get("tradeSettings", {}), s.get("draftSettings", {}))
    scoring = []
    for it in sorted(sc.get("scoringItems", []), key=lambda x: x["statId"]):
        over = {POS.get(int(k), k): v for k, v in (it.get("pointsOverrides") or {}).items()}
        scoring.append({"stat_id": it["statId"], "stat": stat_name(it["statId"]),
                        "points": it["points"], "overrides": over})
    slots = {SLOT.get(int(k), f"slot {k}"): v for k, v in rs["lineupSlotCounts"].items() if v}
    limits = {POS.get(int(k), f"pos {k}"): v for k, v in rs.get("positionLimits", {}).items()
              if int(k) in POS and v not in (-1, None)}
    out = {
        "name": s["name"], "size": s["size"], "public": s.get("isPublic"),
        "scoring_type": sc.get("scoringType"), "scoring": scoring,
        "lineup": slots, "position_max": limits, "lock": rs.get("lineupLocktimeType"),
        "waivers": {"type": aq.get("acquisitionType"), "faab": aq.get("isUsingAcquisitionBudget"),
                    "hours": aq.get("waiverHours"), "order_resets": aq.get("waiverOrderReset"),
                    "process_days": aq.get("waiverProcessDays"), "process_hour": aq.get("waiverProcessHour"),
                    "acquisition_limit": aq.get("acquisitionLimit")},
        "schedule": {"regular_weeks": ss.get("matchupPeriodCount"), "playoff_teams": ss.get("playoffTeamCount"),
                     "seeding": ss.get("playoffSeedingRule"), "reseed": ss.get("playoffReseed"),
                     "playoff_round_weeks": ss.get("playoffMatchupPeriodLength")},
        "trades": {"deadline": local(ts.get("deadlineDate")), "veto_votes": ts.get("vetoVotesRequired"),
                   "review_hours": ts.get("revisionHours"), "max": ts.get("max")},
        "draft": {"date": local(ds.get("date")), "type": ds.get("type"), "clock": ds.get("timePerSelection"),
                  "order": ds.get("orderType"), "keepers": ds.get("keeperCount")},
    }

    def render(o):
        print(f"{o['name']} -- {o['size']} teams, {o['scoring_type']}\n")
        print("  lineup     " + ", ".join(f"{k} x{v}" for k, v in o["lineup"].items()))
        print("  max        " + ", ".join(f"{k} {v}" for k, v in o["position_max"].items()))
        print(f"  locks      {o['lock']}")
        w = o["waivers"]
        print(f"  waivers    {w['type']}, FAAB={w['faab']}, {w['hours']}h period, order resets={w['order_resets']}, "
              f"runs {w['process_hour']}:00 on {', '.join(d[:3].title() for d in (w['process_days'] or []))}")
        sch = o["schedule"]
        print(f"  season     {sch['regular_weeks']} regular weeks; {sch['playoff_teams']} playoff teams, "
              f"{sch['playoff_round_weeks']} week/round, seeding {sch['seeding']}, reseed={sch['reseed']}")
        tr = o["trades"]
        print(f"  trades     deadline {tr['deadline'].strftime('%b %-d %Y') if tr['deadline'] else '-'}, "
              f"{tr['veto_votes']} votes to veto, {tr['review_hours']}h review")
        d = o["draft"]
        print(f"  draft      {d['type']} {d['clock']}s, order {d['order']}, keepers {d['keepers']}, "
              f"{d['date'].strftime('%b %-d %Y %-I:%M %p') if d['date'] else 'unscheduled'}")
        print("\n  scoring:")
        for it in o["scoring"]:
            points, over = it["points"], dict(it["overrides"])
            if points == 0 and len(over) == 1:
                points = next(iter(over.values()))
                over = {}
            tail = ("  [" + ", ".join(f"{k}: {v:+g}" for k, v in over.items()) + "]") if over else ""
            print(f"    {points:>+6g}  {it['stat']}{tail}")
    emit(args, out, render)


def nfl_events(api: Espn, week: int) -> list[dict]:
    d = api.public("site/v2/sports/football/nfl/scoreboard", seasontype=2, week=week, dates=api.season)
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        home = away = None
        for c in comp.get("competitors", []):
            side = {"abbrev": (c.get("team") or {}).get("abbreviation"), "id": (c.get("team") or {}).get("id"),
                    "score": c.get("score"), "winner": c.get("winner"),
                    "record": next((r.get("summary") for r in c.get("records", []) if r.get("type") == "total"), None)}
            if c.get("homeAway") == "home":
                home = side
            else:
                away = side
        odds = (comp.get("odds") or [{}])[0]
        ou, spread = odds.get("overUnder"), odds.get("spread")
        implied_home = implied_away = None
        if ou is not None and spread is not None:
            implied_home = round((ou - spread) / 2, 1)   # spread is from the home side: negative = home favored
            implied_away = round((ou + spread) / 2, 1)
        w = e.get("weather") or {}
        venue = comp.get("venue") or {}
        st = (e.get("status") or {}).get("type") or {}
        out.append({"id": e.get("id"), "name": e.get("shortName"), "kickoff": local_iso(e.get("date")),
                    "home": home, "away": away, "state": st.get("state"), "status": st.get("shortDetail"),
                    "ou": ou, "spread": spread, "line": odds.get("details"),
                    "implied_home": implied_home, "implied_away": implied_away,
                    "indoor": venue.get("indoor"), "venue": venue.get("fullName"),
                    "weather": w.get("displayValue"), "temp": w.get("temperature"),
                    "tv": (comp.get("broadcast") or ""), })
    out.sort(key=lambda g: g["kickoff"] or datetime.max.replace(tzinfo=TZ))
    return out


def local_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)


def cmd_nfl(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    games = nfl_events(api, week)

    def render(games):
        print(f"NFL week {week} -- kickoffs in Central time\n")
        for g in games:
            a, h = g["away"] or {}, g["home"] or {}
            score = ""
            if g["state"] in ("in", "post"):
                score = f"{a.get('abbrev')} {a.get('score')} - {h.get('abbrev')} {h.get('score')}  {g['status']}"
            line = f"{g['line'] or '-':<9} O/U {pts(g['ou']):>5}"
            imp = f"imp {a.get('abbrev')} {pts(g['implied_away'])} / {h.get('abbrev')} {pts(g['implied_home'])}" if g["ou"] is not None else ""
            wx = "dome" if g["indoor"] else (f"{g['temp']}°F {g['weather']}" if g["weather"] else "")
            print(f"  {when(g['kickoff']):<11} {g['name']:<11} {line}  {imp:<24} {wx:<22} {g['tv']:<6} {score}")
        print("\n  imp = implied team total from the spread and total (DraftKings via ESPN). "
              "D/ST: stream against low implied totals. K: favor high own-team totals and domes.")
    emit(args, games, render)


def injury_rows(api: Espn) -> list[dict]:
    d = api.injuries()
    rows = []
    for t in d.get("injuries", []):
        try:
            tid = int(t.get("id"))
        except (TypeError, ValueError):
            tid = None
        for i in t.get("injuries", []):
            a = i.get("athlete") or {}
            det = i.get("details") or {}
            rows.append({"team_id": tid, "team": api.pro(tid)["abbrev"] if tid else t.get("displayName"),
                         "player": a.get("displayName"), "pos": (a.get("position") or {}).get("abbreviation"),
                         "status": i.get("status"), "type": det.get("type"),
                         "fantasy_status": (det.get("fantasyStatus") or {}).get("abbreviation"),
                         "return": det.get("returnDate"), "date": (i.get("date") or "")[:10],
                         "comment": i.get("shortComment")})
    return rows


def cmd_injuries(api: Espn, args: argparse.Namespace) -> None:
    rows = injury_rows(api)
    scope = "all"
    if args.team:
        rows = [r for r in rows if (r["team"] or "").upper() == args.team.upper()]
        scope = args.team.upper()
    elif not args.all:
        data = api.league("mTeam", "mRoster")
        t = api.resolve_team(data, args.mine_team)
        mine = {norm((e.get("playerPoolEntry") or {}).get("player", {}).get("fullName", ""))
                for e in api.roster_entries(data, t["id"])}
        rows = [r for r in rows if norm(r["player"] or "") in mine]
        scope = team_name(t)
    if args.pos:
        rows = [r for r in rows if (r["pos"] or "").upper() == args.pos.upper()]
    elif args.all or args.team:
        rows = [r for r in rows if (r["pos"] or "") in ("QB", "RB", "WR", "TE", "K", "PK")]
    if args.all or args.team:
        # "Active" rows are cleared players with a dated note; only a roster
        # scope wants them (it is worth knowing your RB was listed at all).
        rows = [r for r in rows if (r["status"] or "").lower() != "active"]
    rows.sort(key=lambda r: (r["team"] or "", r["status"] or "", r["player"] or ""))

    def render(rows):
        print(f"NFL injury report -- {scope}\n")
        if not rows:
            print("  (no injuries listed)")
        for r in rows:
            print(f"  {r['team']:<4} {r['player']:<24} {r['pos'] or '':<3} {r['status'] or '':<13} "
                  f"{r['type'] or '':<12} {r['date']}")
            if args.long and r["comment"]:
                print(f"       {r['comment']}")
    emit(args, rows, render)


def cmd_stream(api: Espn, args: argparse.Namespace) -> None:
    week = week_for(api, args)
    pos = "DST" if args.pos.upper() in ("DST", "D/ST") else "K"
    rows = pool_rows(api, week, pos, 40, ["FREEAGENT", "WAIVERS"])
    games = nfl_events(api, week)
    by_pair = {}
    for g in games:
        a, h = (g["away"] or {}).get("abbrev"), (g["home"] or {}).get("abbrev")
        if a and h:
            by_pair[frozenset((a.upper(), h.upper()))] = g
    unmatched = []
    for r in rows:
        r["ou"] = r["implied_own"] = r["implied_opp"] = None
        r["weather"] = ""
        if r["opp"] == "BYE":
            continue
        opp = r["opp"].lstrip("@").upper()
        g = by_pair.get(frozenset((r["team"].upper(), opp)))
        if not g:
            unmatched.append(f"{r['team']} vs {opp}")
            continue
        home = (g["home"] or {}).get("abbrev", "").upper() == r["team"].upper()
        r["ou"] = g["ou"]
        r["implied_own"] = g["implied_home"] if home else g["implied_away"]
        r["implied_opp"] = g["implied_away"] if home else g["implied_home"]
        r["weather"] = "dome" if g["indoor"] else (f"{g['temp']}°F {g['weather']}" if g["weather"] else "")
        r["kickoff"] = g["kickoff"]
    rows = [r for r in rows if r["opp"] != "BYE"]
    rows.sort(key=lambda r: -(r["proj"] or 0))
    rows = rows[: args.n]
    if unmatched:
        warn(f"(no odds matched for: {', '.join(unmatched)})")

    def render(rows):
        label = "D/ST" if pos == "DST" else "K"
        print(f"Streamable {label} -- week {week}, free agents and waivers, by ESPN projection\n")
        for r in rows:
            r["proj_s"] = pts(r["proj"]); r["own_s"] = pts(r["owned"])
            r["ou_s"] = pts(r["ou"]); r["own_imp"] = pts(r["implied_own"]); r["opp_imp"] = pts(r["implied_opp"])
            r["kick"] = when(r.get("kickoff"))
        key_col = ("OPP IMP", "opp_imp", 7, "r") if pos == "DST" else ("OWN IMP", "own_imp", 7, "r")
        table(rows, [("PLAYER", "name", 22, "l"), ("TEAM", "team", 4, "l"), ("OPP", "opp", 5, "l"),
                     ("KICKOFF", "kick", 11, "l"), ("PROJ", "proj_s", 5, "r"), ("O/U", "ou_s", 5, "r"),
                     key_col, ("WEATHER", "weather", 20, "l"), ("%OWN", "own_s", 5, "r"), ("AV", "avail", 3, "l")])
        if pos == "DST":
            print("\n  OPP IMP = the offense they face, implied points. Lower is the streaming target; "
                  "the playbook says avoid high-total games regardless of reputation.")
        else:
            print("\n  OWN IMP = the kicker's own offense, implied points. Higher plus a dome or good "
                  "weather is the target.")
    emit(args, rows, render)


def cmd_raw(api: Espn, args: argparse.Namespace) -> None:
    if args.url:
        headers = api._auth() if "lm-api-reads.fantasy.espn.com" in args.url else None  # noqa: SLF001 -- same package, debugging escape hatch
        if args.filter:
            headers = dict(headers or {}, **{"X-Fantasy-Filter": args.filter})
        data = api._get(args.url, headers)  # noqa: SLF001
    else:
        views = tuple(v for v in args.views.split(",") if v)
        filt = json.loads(args.filter) if args.filter else None
        data = api.league(*views, period=args.period, filt=filt, path=args.path)
    out = json.dumps(data, indent=2)
    if args.limit and len(out) > args.limit:
        print(out[: args.limit])
        warn(f"\n[espn raw: truncated at {args.limit} of {len(out)} chars, so this is not valid JSON. "
             "Pass --limit 0 for all of it.]")
    else:
        print(out)


# ---- entry ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--fresh", action="store_true", help="bypass the day-old caches")
    wk = argparse.ArgumentParser(add_help=False)
    wk.add_argument("--week", type=int, help="scoring period (default: the current one)")
    team = argparse.ArgumentParser(add_help=False)
    team.add_argument("--team", help="team id, abbrev, or name fragment (default: Chaos Legion)")

    ap = argparse.ArgumentParser(prog="espn", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("teams", parents=[common], help="every team: record, owner initials, waiver priority, moves")
    sub.add_parser("team", parents=[common, wk, team], help="a team's roster with weekly projections")
    sub.add_parser("matchup", parents=[common, wk, team], help="this week's matchup, projected margin, variance rule")
    sub.add_parser("scoreboard", parents=[common, wk], help="every matchup this week")
    sub.add_parser("check", parents=[common, wk, team], help="pre-kickoff lineup checklist (inactive, bye, empty, locks)")
    p = sub.add_parser("fa", parents=[common, wk], help="free agents and waivers with projections and ownership")
    p.add_argument("--pos", default="ALL", help="QB RB WR TE K DST FLEX ALL (default ALL)")
    p.add_argument("--sort", default="proj", choices=["proj", "season", "owned", "trend", "points"])
    p.add_argument("-n", type=int, default=25, help="rows to show")
    p.add_argument("--waivers", action="store_true", help="only players still on waivers")
    p = sub.add_parser("player", parents=[common, wk], help="a player's card: status, ownership, projections, log, news")
    p.add_argument("name", nargs="+", help="player name (or ESPN id)")
    p.add_argument("--news", type=int, default=3, help="news items to include (0 = none)")
    p.add_argument("--long", action="store_true", help="print full news stories")
    p = sub.add_parser("news", parents=[common], help="a player's news feed")
    p.add_argument("name", nargs="+")
    p.add_argument("-n", type=int, default=5)
    p.add_argument("--long", action="store_true", help="print full stories")
    p = sub.add_parser("activity", parents=[common], help="league adds, drops, waivers, trades")
    p.add_argument("-n", type=int, default=25)
    p.add_argument("--pending", action="store_true", help="pending waiver claims and trades instead")
    p = sub.add_parser("draft", parents=[common, team], help="draft status, order, and picks")
    p.add_argument("--picks", action="store_true", help="list every pick")
    p.add_argument("--mine", action="store_true", help="only Chaos Legion's picks")
    sub.add_parser("schedule", parents=[common, team], help="a team's head-to-head schedule and results")
    sub.add_parser("settings", parents=[common], help="scoring table, lineup, waivers, playoffs, trades")
    sub.add_parser("nfl", parents=[common, wk], help="NFL slate: kickoffs, lines, implied totals, weather")
    p = sub.add_parser("injuries", parents=[common], help="NFL injury report (default: your roster)")
    p.add_argument("--all", action="store_true", help="every fantasy-relevant player in the league")
    p.add_argument("--team", help="one NFL team by abbreviation")
    p.add_argument("--mine-team", help="fantasy team to scope to (default: Chaos Legion)")
    p.add_argument("--pos", help="filter by position")
    p.add_argument("--long", action="store_true", help="include the report comment")
    p = sub.add_parser("stream", parents=[common, wk], help="D/ST or K streamers with implied totals and weather")
    p.add_argument("--pos", default="DST", help="DST (default) or K")
    p.add_argument("-n", type=int, default=12)
    p = sub.add_parser("raw", parents=[common], help="raw API JSON for building new features")
    p.add_argument("--views", default="mSettings", help="comma-separated ESPN views")
    p.add_argument("--period", type=int, help="scoringPeriodId")
    p.add_argument("--filter", help="X-Fantasy-Filter JSON")
    p.add_argument("--path", default="", help="path under the league, e.g. /players or /communication/")
    p.add_argument("--url", help="any full URL instead (cookies only sent to lm-api-reads)")
    p.add_argument("--limit", type=int, default=4000, help="chars to print; 0 = all")
    return ap


COMMANDS = {
    "teams": cmd_teams, "team": cmd_team, "matchup": cmd_matchup, "scoreboard": cmd_scoreboard,
    "check": cmd_check, "fa": cmd_fa, "player": cmd_player, "news": cmd_news,
    "activity": cmd_activity, "draft": cmd_draft, "schedule": cmd_schedule, "settings": cmd_settings,
    "nfl": cmd_nfl, "injuries": cmd_injuries, "stream": cmd_stream, "raw": cmd_raw,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        api = Espn(fresh=getattr(args, "fresh", False))
        COMMANDS[args.cmd](api, args)
    except EspnError as e:
        print(f"espn: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
