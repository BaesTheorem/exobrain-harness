"""The league log: every team's moves, claims, votes and pending rows, normalized.

ESPN keeps the league's history in three places, and each one shows a
different slice (all checked 2026-10-22, weeks 1-7):

- The activity feed (`kona_league_communication`, ACTIVITY_TRANSACTIONS) has
  every executed add, drop and trade for every team, and every lineup move
  (message 188, about 400 by week 7). It is the only place a completed trade
  between two other teams shows its players: the proposal row itself never
  appears in mTransactions2 for teams that are not ours.
- `mTransactions2`, one scoring period per call, has what the feed leaves out:
  waiver claims that failed or were canceled (for any team, once processed),
  trade votes (TRADE_UPHOLD, TRADE_VETO, with the voter), declines, and the
  canceled copy of a proposal between two other teams (week 2, team 10 to
  team 6). Pending claims and open offers of other teams are never in it.
- `mPendingTransactions` has our own claims and offers, and a trade that two
  other teams accepted while it waits out the league's veto review.

So the log can show the full history for every team, but pending rows only for
us and for trades in review. Another team's open waiver claim or open offer is
not visible to any client.

`normalize()` is a pure function of the raw JSON, and `fantasy/scorebug/wire.js`
is the same function in JavaScript for the Worker. `fantasy/scorebug/test_wire.py`
runs both on one fetch and fails on any difference.

INVARIANTS
- Read-only: GETs through `Espn.league` only.
- Same output as wire.js for the same input (test_wire.py). Change both or neither.
- Owner identities never appear: rows carry team ids, and names come from the
  team table, never from member records.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .client import SLOT, TZ, Espn, local

# Activity feed message types. The team field differs by type (see cli.py's
# ACTIVITY comment, 2026-09-15): adds put the team in "to"; drops in "for",
# with "from" holding the slot the player left; lineup moves (188) put the team
# in "for" and the two slots in "from" and "to"; trade items (224 accepted, 244
# done) run "from" team to "to" team; 245 is a drop the trade forced.
FEED: dict[int, tuple[str, str | None]] = {
    178: ("add", "fa"), 180: ("add", "waiver"),
    179: ("drop", None), 239: ("drop", None), 181: ("drop", "waiver"), 245: ("drop", "trade"),
    188: ("lineup", None), 224: ("trade_accepted", None), 244: ("trade", None),
}
FEED_LIMIT = 1000
# Failed and canceled claims, votes, declines and other teams' ended offers: the
# mTransactions2 rows the feed does not carry. Executed adds, drops and lineup
# rows are skipped there because the feed already has them.
VOTES = {"TRADE_UPHOLD": "uphold", "TRADE_VETO": "veto"}


def feed_filter(limit: int = FEED_LIMIT, offset: int = 0) -> dict:
    return {"topics": {"filterType": {"value": ["ACTIVITY_TRANSACTIONS"]}, "limit": limit,
                       "limitPerMessageSet": {"value": 50}, "offset": offset,
                       "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                       "sortFor": {"sortPriority": 2, "sortAsc": False},
                       "filterIncludeMessageTypeIds": {"value": sorted(FEED)}}}


def week_starts(api: Espn, weeks: int = 18) -> list[int]:
    """Epoch ms at which each fantasy week begins: the Tuesday 00:00 Central on
    or before that week's first NFL kickoff. Index 0 is week 1."""
    first: dict[int, int] = {}
    for pt in api.pro_teams().values():
        for w, games in (pt.get("games") or {}).items():
            for g in games:
                ms = int(g.get("date") or 0)
                if ms and (int(w) not in first or ms < first[int(w)]):
                    first[int(w)] = ms
    out = []
    for w in range(1, weeks + 1):
        if w not in first:
            break
        d = local(first[w])
        assert d is not None
        tue = (d - timedelta(days=(d.weekday() - 1) % 7)).date()
        out.append(int(datetime(tue.year, tue.month, tue.day, tzinfo=TZ).timestamp() * 1000))
    return out


def week_of(ms: int | None, starts: list[int]) -> int | None:
    """The fantasy week an epoch-ms time falls in (0 before week 1)."""
    if ms is None or not starts:
        return None
    w = 0
    for i, s in enumerate(starts):
        if ms >= s:
            w = i + 1
    return w


def fetch_raw(api: Espn, week: int) -> dict[str, Any]:
    """Everything normalize() reads, as ESPN sent it."""
    topics: list[dict] = []
    offset = 0
    while True:
        d = api.league("kona_league_communication", path="/communication/", filt=feed_filter(FEED_LIMIT, offset))
        page = d.get("topics", []) or []
        topics += page
        if len(page) < FEED_LIMIT:
            break
        offset += FEED_LIMIT
    txs: list[dict] = []
    for p in range(1, max(1, week) + 1):
        txs += api.league("mTransactions2", period=p).get("transactions", []) or []
    pending = api.league("mPendingTransactions").get("pendingTransactions", []) or []
    return {"topics": topics, "transactions": txs, "pending": pending}


def _team(m: dict, keys: tuple[str, ...], teams: set[int]) -> int | None:
    for k in keys:
        v = m.get(k)
        if isinstance(v, int) and v in teams:
            return v
    return None


def normalize(raw: dict[str, Any], teams: list[int], me: int, starts: list[int]) -> dict[str, Any]:
    """The raw ESPN rows as one event list (newest first) plus the pending rows.

    Event: id, at (epoch ms), week, team_id, kind, how, player_id,
    other_team_id, detail, src, auto. `auto` marks a row that no person made
    at that moment: a transaction written by an ESPN processor, or a feed row
    whose topic carries no client platform. Those feed rows are ESPN carrying
    out a lineup that a manager set in advance (a FUTURE_ROSTER row, here
    `lineup_plan`) at that week's Tuesday 2:00 AM rollover. Checked
    2026-10-22: Njigba Please!'s executed moves equal its plans in weeks 4, 6
    and 7, and Namaslay's agree on every player both name. ESPN logs them
    under our member id, for a reason it does not document. The plan row
    holds the time the manager made it. Kinds: add, drop, lineup, trade_accepted,
    trade, vote, claim_failed, claim_canceled, offer_declined, offer,
    lineup_plan.
    Pending: id, type, status, team_id, direction (out, in, league),
    process_at, expires_at, proposed_at, order, items."""
    known = set(teams)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for t in raw.get("topics", []):
        auto = not (t.get("creationInfo") or {}).get("platform")
        for m in t.get("messages", []) or []:
            mt = m.get("messageTypeId")
            if mt not in FEED or m.get("id") in seen:
                continue
            seen.add(m["id"])
            kind, how = FEED[mt]
            at = m.get("date") or t.get("date")
            other = None
            detail = None
            if kind == "add":
                team = _team(m, ("to", "for", "from"), known)
            elif kind == "lineup":
                team = _team(m, ("for",), known)
                detail = f"{SLOT.get(m.get('from'), '?')}>{SLOT.get(m.get('to'), '?')}"
            elif kind in ("trade", "trade_accepted"):
                team = _team(m, ("from",), known)
                other = _team(m, ("to",), known)
            elif mt == 245:
                team = _team(m, ("from", "for", "to"), known)
            else:
                team = _team(m, ("for", "from", "to"), known)
            if team is None:
                continue
            events.append({"id": m["id"], "at": at, "week": week_of(at, starts), "team_id": team, "kind": kind,
                           "how": how, "player_id": m.get("targetId"), "other_team_id": other, "detail": detail,
                           "src": "feed", "auto": auto})
    rows: dict[str, dict] = {}
    for x in raw.get("transactions", []):
        if x.get("id"):
            rows[x["id"]] = x
    for x in rows.values():
        typ, st = x.get("type") or "", x.get("status") or ""
        items = x.get("items") or []
        at = x.get("processDate") or x.get("proposedDate")
        base = {"id": x["id"], "at": at, "week": x.get("scoringPeriodId"), "team_id": x.get("teamId"),
                "how": None, "other_team_id": None, "detail": None, "src": "tx",
                "auto": not str(x.get("memberId") or "").startswith("{")}
        if typ == "WAIVER" and st not in ("EXECUTED", "PENDING", ""):
            add = next((i for i in items if i.get("type") == "ADD"), {})
            drop = next((i for i in items if i.get("type") == "DROP"), None)
            events.append({**base, "kind": "claim_canceled" if st == "CANCELED" else "claim_failed",
                           "how": "waiver", "player_id": add.get("playerId"),
                           "detail": st.replace("FAILED_", "").lower() if st != "CANCELED" else None,
                           "drop_id": drop.get("playerId") if drop else None})
        elif typ == "FUTURE_ROSTER":
            # Dated when the manager made the plan; `for_week` is the week it sets.
            made = x.get("proposedDate")
            events.append({**base, "kind": "lineup_plan", "at": made, "week": week_of(made, starts),
                           "player_id": None, "for_week": x.get("scoringPeriodId"),
                           "items": [{"player_id": i.get("playerId"), "from_slot": i.get("fromLineupSlotId"),
                                      "to_slot": i.get("toLineupSlotId")} for i in items]})
        elif typ in VOTES:
            events.append({**base, "kind": "vote", "player_id": None, "detail": VOTES[typ],
                           "related": x.get("relatedTransactionId")})
        elif typ == "TRADE_DECLINE":
            events.append({**base, "kind": "offer_declined", "player_id": None,
                           "related": x.get("relatedTransactionId")})
        elif typ == "TRADE_PROPOSAL" and st in ("CANCELED", "EXECUTED", "PENDING"):
            # Our offers in every state, and another pair's proposal once ESPN
            # shows its canceled copy. A row that is still PENDING here is ours.
            parties = sorted({int(i[k]) for i in items for k in ("fromTeamId", "toTeamId")
                              if isinstance(i.get(k), int) and i[k] in known})
            if st == "PENDING" and me not in parties:
                continue
            other = next((p for p in parties if p != x.get("teamId")), None)
            # ESPN never updates an offer's original row: it stays PENDING after
            # the offer ends, and the end is a second row. So the original reads
            # "proposed", and whether it is still open is the pending list's call.
            detail = "expired" if x.get("memberId") == "TradeTaskProcessor" else (
                "proposed" if st == "PENDING" else st.lower())
            events.append({**base, "kind": "offer", "player_id": None, "other_team_id": other,
                           "detail": detail,
                           "at": x.get("proposedDate"), "related": x.get("relatedTransactionId"),
                           "items": [{"player_id": i.get("playerId"), "from": i.get("fromTeamId"),
                                      "to": i.get("toTeamId")} for i in items if i.get("type") == "TRADE"]})
    events.sort(key=lambda e: (-(e["at"] or 0), e["id"]))
    pending = []
    for p in raw.get("pending", []):
        items = p.get("items") or []
        parties = {i.get(k) for i in items for k in ("fromTeamId", "toTeamId")}
        typ = p.get("type") or ""
        if p.get("teamId") == me:
            direction = "out"
        elif me in parties:
            direction = "in"
        elif typ.startswith("TRADE"):
            direction = "league"
        else:
            continue
        pending.append({"id": p.get("id"), "type": typ, "status": p.get("status"), "team_id": p.get("teamId"),
                        "direction": direction, "process_at": p.get("processDate"),
                        "expires_at": p.get("expirationDate"), "proposed_at": p.get("proposedDate"),
                        "order": p.get("subOrder"),
                        "items": [{"type": i.get("type"), "player_id": i.get("playerId"),
                                   "from": i.get("fromTeamId"), "to": i.get("toTeamId")} for i in items]})
    rank = {"out": 0, "in": 1, "league": 2}      # ours, then offers to us, then trades in review
    pending.sort(key=lambda p: (rank[p["direction"]], p["order"] if p["order"] is not None else 99,
                                p["process_at"] or 0))
    return {"events": events, "pending": pending}


def player_ids(log: dict[str, Any]) -> list[int]:
    ids: set[int] = set()
    for e in log["events"]:
        for k in ("player_id", "drop_id"):
            if isinstance(e.get(k), int):
                ids.add(e[k])
        for i in e.get("items", []):
            if isinstance(i.get("player_id"), int):
                ids.add(i["player_id"])
    for p in log["pending"]:
        for i in p["items"]:
            if isinstance(i.get("player_id"), int):
                ids.add(i["player_id"])
    return sorted(ids)


def names(api: Espn, ids: list[int]) -> dict[int, dict]:
    """id -> {name, pos, nfl} for the players in a log. The index covers active
    players; names_for() fetches cards for the rest (a D/ST, a retired player)."""
    idx = {p["id"]: p for p in api.players_index()}
    out: dict[int, dict] = {}
    miss = []
    for i in ids:
        p = idx.get(i)
        if p:
            out[i] = {"name": p["name"], "pos": p["pos"], "nfl": api.pro(p["team"])["abbrev"]}
        else:
            miss.append(i)
    if miss:
        for i, n in api.names_for(miss).items():
            out[i] = {"name": n, "pos": "D/ST" if i < 0 else "", "nfl": ""}
    return out


def load(api: Espn, week: int | None = None) -> dict[str, Any]:
    """Fetch and normalize, with team ids, our team id and the week starts."""
    data = api.league("mTeam", "mStatus")
    week = week or api.current_week(data)
    teams = [t["id"] for t in data.get("teams", [])]
    me = int(api.creds["team_id"])
    starts = week_starts(api)
    log = normalize(fetch_raw(api, week), teams, me, starts)
    log.update({"week": week, "me": me, "teams": teams, "week_starts": starts})
    return log
