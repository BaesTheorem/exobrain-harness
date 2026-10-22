"""Rival analysis behind `fantasy/bin/rival-scan` and the Scorebug Wire tab.

The CLI's docstring (fantasy/bin/rival-scan) describes each section and the
measurements behind it. This module holds the logic so that the Scorebug
snapshot (fantasy/scorebug/snapshot.py) can post the same analysis.

INVARIANTS
- Read-only against ESPN. It never files, cancels or proposes anything.
- No owner names: teams by team name, the prediction log by team id.
- Every value is espncli.value.ros_rate, the one in-season currency.
"""

from __future__ import annotations

import collections
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import league_log
from .cli import empty_slot_rows, lineup_problems, pool_rows, slot_counts, table, week_rows
from .client import BENCH, IR, SLOT_BY_NAME, Espn, local, team_name
from .value import games_played, ros_rate

FANTASY = Path(__file__).resolve().parent.parent
LEAGUE_SCAN = FANTASY / "bin" / "league-scan"

LOG = FANTASY / "forecasts"
DAY = 86400_000
RECYCLED_DAYS = 4          # a drop this recent makes a waiver player "recycled"
USER_KINDS = {"lineup", "offer", "vote", "offer_declined"}
UNFIT = ("OUT", "IR", "SUSP", "D")


def ago(ms: int | None, now_ms: int) -> str:
    if not ms:
        return "-"
    h = (now_ms - ms) / 3600_000
    return f"{h:.0f}h" if h < 48 else f"{h / 24:.0f}d"


def at_s(ms: int | None) -> str:
    d = local(ms)
    if not d:
        return "-"
    fmt = "%a %-I:%M%p" if abs(time.time() - d.timestamp()) < 6 * 86400 else "%-m/%-d %-I:%M%p"
    return d.strftime(fmt).replace("AM", "a").replace("PM", "p")


def user_event(e: dict) -> bool:
    """Something the manager did by hand, with a real time stamp. A processed
    waiver add or drop carries the run's time, not the manager's."""
    if e.get("auto"):
        return False
    return e["kind"] in USER_KINDS or (e["kind"] in ("add", "drop") and e["how"] not in ("waiver", "trade"))


def window(events: list[dict]) -> str | None:
    """The weekday and three-hour band in which a manager acts most."""
    c: collections.Counter = collections.Counter()
    for e in events:
        d = local(e["at"])
        if d:
            c[(d.strftime("%a"), d.hour // 3)] += 1
    if not c:
        return None
    (day, band), n = c.most_common(1)[0]
    h0, h1 = band * 3, band * 3 + 3
    fmt = lambda h: f"{(h % 12) or 12}{'a' if h % 24 < 12 else 'p'}"
    return f"{day} {fmt(h0)}-{fmt(h1)} ({n} of {sum(c.values())})"


def needs(rows: list[dict], counts: dict[int, int]) -> list[dict]:
    """Starter problems (lineup_problems) with the bench cover for each. A
    covered hole is a lineup fix; an uncovered one is a need from the wire.
    lineup_problems skips a starter whose game has started (he has an actual)."""
    full = rows + empty_slot_rows(rows, counts)
    bench = [r for r in rows if r["slotId"] == BENCH and r["opp"] != "BYE" and r["status"] not in UNFIT
             and not r.get("locked")]
    out = []
    used: set = set()
    for p in lineup_problems(full):
        sid = SLOT_BY_NAME.get(p["slot"])
        cover = next((b for b in bench if sid in (b.get("eligible") or []) and b["id"] not in used), None)
        if cover:
            used.add(cover["id"])
        out.append({"slot": p["slot"], "pos": "RB/WR/TE" if p["slot"] == "FLEX" else p["slot"], "kind": p["kind"],
                    "player": p["player"], "cover": cover["name"] if cover else None})
    return out


def fits(pos: str, need: list[str]) -> bool:
    return pos in need or (pos in ("RB", "WR", "TE") and "RB/WR/TE" in need)


def base_rates(events: list[dict], names: dict[int, dict]) -> dict[str, list[int]]:
    """pos -> [claimed off waivers by another team, dropped]: each drop in this
    league and whether a different team claimed that player in the next
    RECYCLED_DAYS days."""
    ev = sorted(events, key=lambda e: e["at"] or 0)
    adds: dict[int, list[dict]] = collections.defaultdict(list)
    for e in ev:
        if e["kind"] == "add":
            adds[e["player_id"]].append(e)
    out: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for d in ev:
        if d["kind"] != "drop" or d["how"] == "trade" or not d["week"]:
            continue
        pos = names.get(d["player_id"], {}).get("pos") or "?"
        nxt = next((a for a in adds[d["player_id"]] if a["at"] > d["at"]), None)
        out[pos][1] += 1
        if nxt and nxt["how"] == "waiver" and nxt["team_id"] != d["team_id"] and nxt["at"] - d["at"] < RECYCLED_DAYS * DAY:
            out[pos][0] += 1
    return dict(out)


def p_claimed(pos: str, rates: dict[str, list[int]]) -> float:
    """The league's rate for a dropped player at `pos`, with one claim and one
    non-claim added to the count, so 0 of 11 reads as 1 in 13, not as never."""
    k, n = rates.get(pos, [0, 0])
    return (k + 1) / (n + 2)


def build(api: Espn) -> tuple[dict[str, Any], list[dict]]:
    now_ms = int(time.time() * 1000)
    data = api.league("mTeam", "mSettings", "mStatus", "mMatchup")
    week = api.current_week(data)
    me = int(api.creds["team_id"])
    counts = slot_counts(data)
    active_max = sum(n for s, n in counts.items() if s != IR)
    log = league_log.load(api, week)
    names = league_log.names(api, league_log.player_ids(log))
    events = log["events"]

    try:
        ls = json.loads(subprocess.run([sys.executable, str(LEAGUE_SCAN), "--json"], capture_output=True,
                                       text=True, timeout=180).stdout)
        scan = {t["team_id"]: t for t in ls["teams"]}
    except Exception:  # noqa: BLE001 - the board still stands without the engagement columns
        scan = {}

    _, now_rows = week_rows(api, week)
    _, next_rows = week_rows(api, week + 1)
    weeks_elapsed = max(1.0, (now_ms - log["week_starts"][0]) / (7 * DAY)) if log["week_starts"] else float(week)

    standing = []
    for t in data["teams"]:
        r = t.get("record", {}).get("overall", {})
        g = max(r.get("wins", 0) + r.get("losses", 0) + r.get("ties", 0), 1)
        standing.append((-(r.get("wins", 0) + r.get("ties", 0) / 2) / g, -r.get("pointsFor", 0.0), t["id"]))
    rank = {tid: i for i, (_, _, tid) in enumerate(sorted(standing), 1)}
    sched = {}
    for m in data.get("schedule", []):
        for k in ("home", "away"):
            if m.get(k):
                o = m.get("away" if k == "home" else "home")
                sched[(m["matchupPeriodId"], m[k]["teamId"])] = o["teamId"] if o else None

    board = []
    for t in data["teams"]:
        tid = t["id"]
        r = t.get("record", {}).get("overall", {})
        mine = [e for e in events if e["team_id"] == tid]
        hand = [e for e in mine if user_event(e)]
        adds = [e for e in mine if e["kind"] == "add"]
        rows = now_rows.get(tid, [])
        active = sum(1 for x in rows if x["slotId"] != IR)
        s = scan.get(tid, {})
        this_week = needs(rows, counts)
        nxt = needs(next_rows.get(tid, []), counts)
        board.append({
            "team_id": tid, "team": team_name(t), "abbrev": t.get("abbrev"), "mine": tid == me,
            "rank": rank[tid], "priority": t.get("waiverRank"),
            "record": f"{r.get('wins', 0)}-{r.get('losses', 0)}" + (f"-{r['ties']}" if r.get("ties") else ""),
            "pf": round(r.get("pointsFor", 0.0), 1), "w": r.get("wins", 0) + r.get("ties", 0) / 2,
            "opponent_id": sched.get((week, tid)), "next_opponent_id": sched.get((week + 1, tid)),
            "open_spots": max(0, active_max - active) if rows else None,
            "holes": this_week, "holes_next": nxt,
            "needs": sorted({h["pos"] for h in this_week if not h["cover"]}),
            "needs_next": sorted({h["pos"] for h in nxt if not h["cover"]}),
            "adds": len(adds), "adds_fa": sum(1 for e in adds if e["how"] == "fa"),
            "adds_pw": round(len(adds) / weeks_elapsed, 2),
            "claims": sum(1 for e in mine if (e["kind"] == "add" and e["how"] == "waiver")
                          or e["kind"] in ("claim_failed", "claim_canceled")),
            "kdst_adds": sum(1 for e in adds if names.get(e["player_id"], {}).get("pos") in ("K", "D/ST")),
            "lineup_weeks": len({e["week"] for e in mine if e["kind"] == "lineup" and e["week"] and not e.get("auto")}),
            "moves_this_week": sum(1 for e in hand if e["kind"] != "lineup" and e["week"] == week)
                               + sum(1 for e in mine if e["kind"] == "add" and e["how"] == "waiver" and e["week"] == week),
            "last_seen": max((e["at"] for e in hand), default=None),
            "acts": window([e for e in hand]),
            "recent": [e["id"] for e in mine if e["kind"] in ("add", "drop", "trade", "claim_failed")][:4],
            "tier": s.get("tier"), "fix": [s.get("bye_fixed"), s.get("bye_holes")] if s else None,
            "zeros": s.get("zeros"), "left_pw": s.get("left_pw"), "vs_proj_pw": s.get("vs_proj_pw"),
            "offers_recv": s.get("offers_recv"), "offers_expired": s.get("expired"),
        })
    board.sort(key=lambda b: b["priority"] or 99)
    by_id = {b["team_id"]: b for b in board}
    ours = by_id[me]

    # ---- wire ----
    rates = base_rates(events, names)
    pro_games = {pt["abbrev"]: games_played(pt["games"], week) for pt in api.pro_teams().values()}
    pend = {i["player_id"]: p for p in log["pending"] if p["direction"] == "out" and p["type"] == "WAIVER"
            for i in p["items"] if i["type"] == "ADD"}
    last_drop: dict[int, dict] = {}
    for e in events:            # newest first
        if e["kind"] == "drop" and e["player_id"] not in last_drop:
            last_drop[e["player_id"]] = e
    wire = []
    for p in pool_rows(api, week, "ALL", 60, ["WAIVERS"]):
        rate = ros_rate(week, p.get("proj"), p.get("season_proj"), p.get("season_actual"), pro_games.get(p["team"]))
        d = last_drop.get(p["id"])
        recycled = bool(d and now_ms - (d["at"] or 0) < RECYCLED_DAYS * DAY)
        pos = p["pos"]
        rivals = [b["team_id"] for b in board if not b["mine"]
                  and (fits(pos, b["needs"]) or fits(pos, b["needs_next"]))]
        ahead = [t for t in rivals if (by_id[t]["priority"] or 99) < (ours["priority"] or 99)]
        po = p_claimed(pos, rates) if recycled else None
        wire.append({"player_id": p["id"], "name": p["name"], "pos": pos, "nfl": p["team"], "rate": round(rate, 2),
                     "proj": p.get("proj"), "owned": p.get("owned"), "trend": p.get("trend"),
                     "clears": int(p["clears"].timestamp() * 1000) if p.get("clears") else None,
                     "dropped_by": d["team_id"] if d else None, "dropped_at": d["at"] if d else None,
                     "class": "recycled" if recycled else "fresh", "need_teams": rivals, "need_ahead": ahead,
                     "p_other": round(po, 3) if po is not None else None,
                     "ours": p["id"] in pend, "lands": round(1 - po, 3) if (po is not None and p["id"] in pend) else None})
    wire.sort(key=lambda w: (not w["ours"], -w["rate"]))
    wire = [w for w in wire if w["ours"] or w["rate"] >= 3.0 or w["class"] == "recycled"][:20]

    # ---- opponent: this week, or next week's in an idle week ----
    opp_id, opp_week = ours["opponent_id"], week
    if opp_id is None:
        opp_id, opp_week = ours["next_opponent_id"], week + 1
    opponent = None
    if opp_id:
        ob = by_id[opp_id]
        holes = ob["holes"] if opp_week == week else ob["holes_next"]
        rate_fix = ((ob["fix"][0] or 0) + 1) / ((ob["fix"][1] or 0) + 2) if ob.get("fix") else 0.5
        fills = []
        for h in holes:
            if h["cover"]:
                continue
            slot = {"D/ST": "DST", "RB/WR/TE": "FLEX"}.get(h["pos"]) or h["pos"] or "ALL"
            try:
                fa = [x for x in pool_rows(api, opp_week, slot, 20, ["FREEAGENT"])
                      if x["opp"] != "BYE" and x["status"] not in UNFIT]
            except SystemExit:
                fa = []
            fa.sort(key=lambda x: -(x.get("proj") or 0))
            if fa:
                gap = (fa[0].get("proj") or 0) - (fa[1].get("proj") or 0 if len(fa) > 1 else 0)
                fills.append({"slot": h["slot"], "player": h["player"], "kind": h["kind"], "best": fa[0]["name"],
                              "best_proj": round(fa[0].get("proj") or 0, 1),
                              "next": fa[1]["name"] if len(fa) > 1 else None,
                              "gap": round(gap, 1), "denial_pts": round(gap * rate_fix, 2)})
        opponent = {"team_id": opp_id, "week": opp_week, "fix_rate": round(rate_fix, 2), "fills": fills}

    # ---- race: within a game of the #2 seed ----
    second = sorted(board, key=lambda b: b["rank"])[1]
    race = [b["team_id"] for b in sorted(board, key=lambda b: b["rank"])
            if not b["mine"] and b["w"] >= second["w"] - 1][:5]

    # ---- market ----
    trades = [e for e in events if e["kind"] in ("trade", "trade_accepted")]
    market = {"in_review": [p for p in log["pending"] if p["direction"] == "league"],
              "ours": [p for p in log["pending"] if p["type"].startswith("TRADE") and p["direction"] != "league"],
              "trades": [e["id"] for e in trades][:12],
              "votes": [e["id"] for e in events if e["kind"] == "vote"][:12],
              "seen_offers": [e["id"] for e in events if e["kind"] == "offer" and me not in
                              ({i["from"] for i in e.get("items", [])} | {i["to"] for i in e.get("items", [])})][:12]}

    changes = [e["id"] for e in events if e["team_id"] != me and e["kind"] not in ("lineup",)
               and now_ms - (e["at"] or 0) < 2 * DAY]
    last_run = max((e["at"] for e in events if e["kind"] == "add" and e["how"] == "waiver"), default=None)
    out = {"at": now_ms, "week": week, "me": me, "board": board, "wire": wire, "opponent": opponent, "race": race,
           "market": market, "changes": changes, "last_run": last_run, "base_rates": rates,
           "next_run": min((w["clears"] for w in wire if w["clears"]), default=None),
           "week_starts": log["week_starts"],
           # The claims, votes and offers the Worker does not re-read for every
           # past week; it reads the feed and the last two weeks live.
           "tx_events": [e for e in events if e["src"] == "tx"],
           "events": {e["id"]: e for e in events if e["id"] in set(changes) | set(market["trades"]) |
                      set(market["votes"]) | set(market["seen_offers"]) | {i for b in board for i in b["recent"]}},
           "names": {str(k): v for k, v in names.items()}}
    out["brief"] = brief(out)
    return out, events


# ---- text ----------------------------------------------------------------

def short(b: dict, tid: Any = "?") -> str:
    """The abbreviation, unless it is one or two letters ("O" reads as zero)."""
    ab = b.get("abbrev") or ""
    return ab if len(ab) >= 3 else (b.get("team") or ab or str(tid))


def say(out: dict, eid: str) -> str:
    e = out["events"][eid]
    by = {b["team_id"]: b for b in out["board"]}
    nm = out["names"].get(str(e.get("player_id")), {}).get("name") or "?"
    who = short(by.get(e["team_id"], {}), e["team_id"])
    k = e["kind"]
    if k == "add":
        return f"{who} +{nm}" + (" (waiver)" if e["how"] == "waiver" else "")
    if k == "drop":
        return f"{who} -{nm}"
    if k in ("trade", "trade_accepted"):
        return f"{who} sends {nm} to {short(by.get(e['other_team_id'], {}))}" + (" (in review)" if k == "trade_accepted" else "")
    if k == "claim_failed":
        return f"{who} lost a claim on {nm}"
    if k == "claim_canceled":
        return f"{who} canceled a claim on {nm}"
    if k == "vote":
        return f"{who} voted {e['detail']}"
    if k == "offer":
        return f"{who} offered {short(by.get(e['other_team_id'], {}))} a trade ({e['detail']})"
    if k == "offer_declined":
        return f"{who} declined an offer"
    return f"{who} {k} {nm}"


def brief(out: dict) -> list[str]:
    by = {b["team_id"]: b for b in out["board"]}
    me = by[out["me"]]
    now_ms = out["at"]
    lines = [f"League read, week {out['week']}: we pick {me['priority']} of {len(out['board'])}"
             + (f", next waiver run {at_s(out['next_run'])}" if out.get("next_run") else "") + "."]
    moves = [say(out, i) for i in out["changes"]]
    lines.append("Rival moves, 48h: " + ("; ".join(moves[:8]) + (f" (+{len(moves) - 8} more)" if len(moves) > 8 else "")
                                         if moves else "none."))
    for w in [w for w in out["wire"] if w["ours"]]:
        rate = out["base_rates"].get(w["pos"], [0, 0])
        ahead = ", ".join(by[t]["team"] for t in w["need_ahead"]) or "no team"
        if w["class"] == "recycled":
            lines.append(f"Our claim {w['name']} ({w['pos']}): this league claimed {rate[0]} of {rate[1]} dropped "
                         f"{w['pos']}s off waivers; {ahead} ahead of us has a {w['pos']} need; lands about {round(100 * (w['lands'] or 0))}%.")
        else:
            lines.append(f"Our claim {w['name']} ({w['pos']}): never dropped here, so rivals with a {w['pos']} need "
                         f"({ahead}) can claim him first; a breakout draws several claims in this league.")
    o = out.get("opponent")
    if o:
        ob = by[o["team_id"]]
        holes = [f"{h['slot']} {h['kind'].lower()} ({h['player']}{', bench covers' if h['cover'] else ''})"
                 for h in (ob["holes"] if o["week"] == out["week"] else ob["holes_next"])]
        fill = "; ".join(f"best FA {f['best']} {f['best_proj']} (next {f['gap']} lower)" for f in o["fills"])
        lines.append(f"Opponent week {o['week']}, {ob['team']} ({ob['record']}, {ob.get('tier') or '?'}, fix rate "
                     f"{o['fix_rate']}, last seen {ago(ob['last_seen'], now_ms)} ago): "
                     + ("; ".join(holes) if holes else "no holes") + (f". {fill}" if fill else "") + ".")
    race = [by[t] for t in out["race"]]
    if race:
        def need(b: dict) -> str:
            n = ([f"{', '.join(b['needs'])} now"] if b["needs"] else []) + (
                [f"{', '.join(b['needs_next'])} in week {out['week'] + 1}"] if b["needs_next"] else [])
            return f" needs {' and '.join(n)}" if n else ""
        lines.append("Bye race: " + "; ".join(f"{b['team']} {b['record']}{need(b)}" for b in race) + ".")
    m = out["market"]
    if m["in_review"]:
        lines.append(f"TRADE IN REVIEW: {len(m['in_review'])} (veto window open; `rival-scan` for the players).")
    return lines


def render(out: dict) -> None:
    now_ms = out["at"]
    by = {b["team_id"]: b for b in out["board"]}
    print("\n".join(out["brief"]))
    print("\nBoard (waiver order)\n")
    rows = []
    for b in out["board"]:
        rows.append({**b, "fix_s": f"{b['fix'][0]}/{b['fix'][1]}" if b.get("fix") else "-",
                     "need_s": ",".join(b["needs"]) or "-", "next_s": ",".join(b["needs_next"]) or "-",
                     "seen": ago(b["last_seen"], now_ms), "mark": "<- us" if b["mine"] else ""})
    table(rows, [("WVR", "priority", 3, "r"), ("#", "rank", 2, "r"), ("TEAM", "team", 22, "l"), ("W-L", "record", 5, "l"),
                 ("TIER", "tier", 9, "l"), ("FIX", "fix_s", 5, "r"), ("ADD", "adds", 3, "r"), ("K/D", "kdst_adds", 3, "r"),
                 ("CLM", "claims", 3, "r"), ("LUW", "lineup_weeks", 3, "r"), ("SEEN", "seen", 4, "r"),
                 ("NEEDS", "need_s", 9, "l"), ("NEXT WK", "next_s", 9, "l"), ("ACTS", "acts", 20, "l"), ("", "mark", 5, "l")])
    print("\n  FIX = bye holes fixed of faced. K/D = K and D/ST adds. CLM = waiver claims, won and lost. LUW = weeks "
          "with a lineup move. NEEDS = an uncovered hole this week; NEXT WK = next week's bye or injury hole.")
    print("\nWire (players on waivers)\n")
    for w in out["wire"]:
        rate = out["base_rates"].get(w["pos"], [0, 0])
        tag = " OUR CLAIM" if w["ours"] else ""
        who = ", ".join(short(by[t]) for t in w["need_teams"]) or "none"
        base = (f"recycled: {rate[0]}/{rate[1]} dropped {w['pos']}s were claimed, p {w['p_other']}"
                if w["class"] == "recycled" else "fresh")
        print(f"  {w['name']:<24} {w['pos']:<4} {w['nfl']:<4} rate {w['rate']:<5} clears {at_s(w['clears']):<10} "
              f"{base}; need: {who}{tag}")
    if out.get("opponent") and out["opponent"]["fills"]:
        print("\nOpponent's open holes and the free agent who fills each\n")
        for f in out["opponent"]["fills"]:
            print(f"  {f['slot']:<5} {f['player']:<22} {f['kind']:<8} best {f['best']} {f['best_proj']}, next {f['next']} "
                  f"({f['gap']} lower): denial worth {f['denial_pts']} pts at their fix rate")
    m = out["market"]
    print("\nMarket\n")
    for p in m["in_review"]:
        print(f"  IN REVIEW, processes {at_s(p['process_at'])}: " + ", ".join(
            f"{out['names'].get(str(i['player_id']), {}).get('name', i['player_id'])} "
            f"{by.get(i['from'], {}).get('abbrev', '?')}>{by.get(i['to'], {}).get('abbrev', '?')}" for i in p["items"]))
    for i in m["trades"][:6]:
        print(f"  {at_s(out['events'][i]['at']):<11} {say(out, i)}")
    for i in m["votes"][:4] + m["seen_offers"][:4]:
        print(f"  {at_s(out['events'][i]['at']):<11} {say(out, i)}")
    if not (m["in_review"] or m["trades"] or m["votes"] or m["seen_offers"]):
        print("  (quiet)")


# ---- predictions ---------------------------------------------------------

def log_path(season: int) -> Path:
    return LOG / f"rivals-{season}.jsonl"


def record(api: Espn, out: dict) -> int:
    path = log_path(api.season)
    have = set()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            have.add((r["player_id"], r["clears"]))
    n = 0
    with path.open("a") as f:
        for w in out["wire"]:
            if not w["clears"] or (w["player_id"], w["clears"]) in have:
                continue
            f.write(json.dumps({"at": out["at"], "week": out["week"], "player_id": w["player_id"], "pos": w["pos"],
                                "class": w["class"], "p_other": w["p_other"], "ours": w["ours"],
                                "need_teams": w["need_teams"], "trend": w["trend"], "rate": w["rate"],
                                "clears": w["clears"], "outcome": None}) + "\n")
            n += 1
    return n


def settle(api: Espn) -> dict:
    """Score each recorded wire row whose run has passed: was the player
    claimed by another team, and did our claim land."""
    path = log_path(api.season)
    if not path.exists():
        return {"settled": 0, "rows": 0}
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    now_ms = int(time.time() * 1000)
    todo = [r for r in rows if r["outcome"] is None and r["clears"] + 6 * 3600_000 < now_ms]
    if todo:
        log = league_log.load(api)
        me = log["me"]
        for r in todo:
            hits = [e for e in log["events"] if e["player_id"] == r["player_id"] and e["kind"] == "add"
                    and e["how"] == "waiver" and abs((e["at"] or 0) - r["clears"]) < 12 * 3600_000]
            r["outcome"] = {"other": any(e["team_id"] != me for e in hits), "ours": any(e["team_id"] == me for e in hits)}
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    done = [r for r in rows if r["outcome"]]
    rec = [r for r in done if r["class"] == "recycled" and r["p_other"] is not None]
    brier = sum((r["p_other"] - (1.0 if r["outcome"]["other"] else 0.0)) ** 2 for r in rec) / len(rec) if rec else None
    fresh = [r for r in done if r["class"] == "fresh"]
    return {"settled": len(todo), "rows": len(rows), "recycled": len(rec),
            "recycled_claimed": sum(1 for r in rec if r["outcome"]["other"]),
            "recycled_mean_p": round(sum(r["p_other"] for r in rec) / len(rec), 3) if rec else None,
            "brier": round(brier, 4) if brier is not None else None,
            "fresh": len(fresh), "fresh_claimed": sum(1 for r in fresh if r["outcome"]["other"]),
            "ours": sum(1 for r in done if r["ours"]), "ours_landed": sum(1 for r in done if r["ours"] and r["outcome"]["ours"])}


CACHE_TTL = 3600


def cached(api: Espn, fresh: bool = False) -> dict[str, Any]:
    """The last build, rebuilt when older than an hour (or when `fresh`). The
    snapshot posts this to the Scorebug Worker; rival-scan refreshes it."""
    if fresh:
        out, _ = build(api)
        save(api, out)
        return out
    return api._cached("rivals", lambda: build(api)[0], ttl=CACHE_TTL)  # noqa: SLF001 - the package's own cache


def save(api: Espn, out: dict[str, Any]) -> None:
    """Write a build where cached() reads it (the client's cache file name)."""
    f = FANTASY / ".cache" / f"rivals-{api.season}.json"
    f.parent.mkdir(exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, default=str))
    tmp.replace(f)
