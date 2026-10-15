"""props: player prop lines, the betting market's forecast of every box score.

A sportsbook line is a forecast with money behind it, set by people paid to
be right and moved by bettors paid when it is wrong. ESPN's core API carries
the book's player props for every NFL game, past games included:

    sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/<id>/
        competitions/<id>/odds/<provider>/propBets?limit=1000&page=N

Provider 58 (ESPN BET) for 2024 and 2025, with prices on the main line;
provider 100 (DraftKings) from 2026, lines only. Provider 59 is in-game
("Live Odds") and is never read: a line set after kickoff knows the score.
Each item carries `open` and `current`; for a finished game `current` is the
last pregame number, the close. (Checked 2026-10-15: the DraftKings feed has
no live provider beside it, so `backtest` measures whether the close is
suspiciously close to the outcome before trusting it.)

    crawl(season, weeks)   pull every finished game's props into
                           .cache/props/<season>.jsonl.gz (resumable; one
                           line per game, compact rows, no prices dropped)
    lines(seasons)         one row per player-game-stat: the main line (the
                           priced one when prices exist, else the line the
                           book posts both sides of), its de-vigged P(over),
                           at the open and at the close

The main line is the market median when the two sides are priced evenly;
with prices, P(over) moves it. `ffmodel.market` turns lines into fantasy points.

INVARIANTS
- Read-only, and only the pregame providers. A row from provider 59 never
  enters the cache.
- Unpriced alternate ladders (the 149.5 ... 349.5 rungs) are never mistaken
  for the main line: with prices, the main line is the priced target; without
  prices, it is the target posted for both sides, else the only target.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "props"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"}
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
SITE = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl"
PREGAME = {"58", "100"}            # ESPN BET (to 2025), DraftKings (2026 on)
LIVE = {"59"}
# Prop types kept. Ladders ("Milestones"), quarters and halves, longest-play
# and defensive props carry no information the main lines lack here.
KEEP = {
    "8": "pass_yds", "9": "completions", "10": "pass_td", "11": "carries", "12": "rush_yds",
    "13": "rec_yds", "14": "receptions", "15": "ints", "16": "pass_att", "18": "pass_rush_yds",
    "20": "rush_rec_yds", "22": "kick_pts", "23": "pat_made", "24": "fg_made", "31": "anytime_td",
    "98": "team_pts", "104": "team_tds",
}
PAUSE = 0.25                        # seconds between requests: about 4 a second


def get(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
        time.sleep(2 ** i)
    return {}


def events(season: int, week: int) -> list[dict]:
    d = get(f"{SITE}/scoreboard?week={week}&seasontype=2&dates={season}")
    out = []
    for e in d.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): (c.get("team") or {}).get("abbreviation") for c in comp.get("competitors", [])}
        st = ((e.get("status") or {}).get("type") or {}).get("state")
        out.append({"id": str(e["id"]), "week": week, "kickoff": e.get("date"), "state": st,
                    "home": teams.get("home"), "away": teams.get("away")})
    return out


def _ref_id(obj: dict | None, key: str) -> str | None:
    ref = (obj or {}).get("$ref") or ""
    marker = f"/{key}/"
    return ref.split(marker)[1].split("?")[0] if marker in ref else None


def _price(side: dict | None) -> float | None:
    if not side:
        return None
    raw = side.get("decimal") or side.get("value")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def compact(item: dict, provider: str) -> dict | None:
    t = (item.get("type") or {}).get("id")
    if t not in KEEP:
        return None
    row: dict[str, Any] = {"p": provider, "t": KEEP[t],
                           "a": _ref_id(item.get("athlete"), "athletes"), "tm": _ref_id(item.get("team"), "teams"),
                           "u": item.get("lastUpdated")}
    for when in ("open", "current"):
        side = item.get(when) or {}
        tgt = (side.get("target") or {}).get("value")
        row[when[0] + "l"] = tgt
        row[when[0] + "o"] = _price(side.get("over"))
        row[when[0] + "u"] = _price(side.get("under"))
    if row["ol"] is None and row["cl"] is None and row["oo"] is None and row["co"] is None:
        return None
    return row


def game_props(event_id: str) -> list[dict]:
    odds = get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds?lang=en&region=us")
    rows: list[dict] = []
    for it in odds.get("items", []):
        prov = str((it.get("provider") or {}).get("id"))
        if prov in LIVE or prov not in PREGAME or "propBets" not in it:
            continue
        page = 1
        while True:
            time.sleep(PAUSE)
            d = get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds/{prov}/propBets"
                    f"?lang=en&region=us&limit=1000&page={page}")
            for item in d.get("items", []):
                r = compact(item, prov)
                if r:
                    rows.append(r)
            if page >= int(d.get("pageCount") or 1):
                break
            page += 1
    return rows


def cache_file(season: int) -> Path:
    return CACHE / f"{season}.jsonl.gz"


def done_games(season: int) -> set[str]:
    """Games already cached with rows. A game cached empty (the feed had no
    props for it at crawl time) is crawled again next run."""
    return {g["game"] for g in games_cached([season]) if g["rows"]}


def crawl(season: int, weeks: list[int], verbose: bool = True) -> int:
    """Append every finished, not-yet-cached game of `weeks` to the cache."""
    CACHE.mkdir(parents=True, exist_ok=True)
    have = done_games(season)
    added = 0
    for w in weeks:
        for ev in events(season, w):
            if ev["state"] != "post" or ev["id"] in have:
                continue
            time.sleep(PAUSE)
            rows = game_props(ev["id"])
            with gzip.open(cache_file(season), "at") as f:
                f.write(json.dumps({"game": ev["id"], "season": season, **ev, "rows": rows}) + "\n")
            have.add(ev["id"])
            added += 1
            if verbose:
                print(f"props: {season} w{w:02d} {ev['away']}@{ev['home']} {len(rows)} rows", file=sys.stderr, flush=True)
    return added


def games_cached(seasons: list[int]) -> list[dict]:
    """Every cached game, one record per game id: a later non-empty record
    replaces an earlier empty one."""
    out: dict[str, dict] = {}
    for s in seasons:
        path = cache_file(s)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as f:
            for line in f:
                if not line.strip():
                    continue
                g = json.loads(line)
                if g["rows"] or g["game"] not in out:
                    out[g["game"]] = g
    return list(out.values())


def devig(over: float | None, under: float | None) -> float | None:
    """P(over) with the book's margin removed (proportional), from decimal odds."""
    if not over or not under or over <= 1 or under <= 1:
        return None
    a, b = 1 / over, 1 / under
    return a / (a + b)


def main_line(items: list[dict], when: str) -> tuple[float | None, float | None]:
    """(line, P(over)) for one player-game-stat at `when` ("o" open, "c" close).

    Priced rows win: the target with both sides priced, de-vigged; a target
    priced on one side only is still the main line, with P(over) unknown.
    With no prices at all (the 2026 feed), the target posted twice (over and
    under) is the main line; a lone target is taken as it is."""
    lk, ok, uk = when + "l", when + "o", when + "u"
    priced: dict[float, dict[str, float]] = defaultdict(dict)
    counts: dict[float, int] = defaultdict(int)
    for it in items:
        tgt = it.get(lk)
        if tgt is None:
            continue
        counts[float(tgt)] += 1
        if it.get(ok):
            priced[float(tgt)]["o"] = it[ok]
        if it.get(uk):
            priced[float(tgt)]["u"] = it[uk]
    if priced:
        both = [t for t, s in priced.items() if "o" in s and "u" in s]
        if both:
            # Several priced targets is rare; the one nearest even money is the main line.
            best = min(both, key=lambda t: abs((devig(priced[t]["o"], priced[t]["u"]) or 0.5) - 0.5))
            return best, devig(priced[best]["o"], priced[best]["u"])
        return next(iter(priced)), None
    if not counts:
        return None, None
    twice = [t for t, c in counts.items() if c >= 2]
    if len(twice) == 1:
        return twice[0], None
    if len(counts) == 1:
        return next(iter(counts)), None
    return None, None


def anytime_prob(items: list[dict], when: str) -> float | None:
    """P(at least one TD) from the anytime market when it is priced. The book
    posts it one-sided, so the margin is taken off with a flat 5% haircut on
    the implied probability (the typical anytime-TD overround per side)."""
    ok = when + "o"
    for it in items:
        if it.get(ok) and (it.get(when + "l") in (None, 0.5)):
            return min(0.97, (1 / it[ok]) / 1.05)
    return None


def lines(seasons: list[int]):
    """One row per (game, athlete or team, stat): open and close main lines.

    Columns: season, week, game, kickoff, home, away, athlete, team_id, stat,
    open_line, open_p, close_line, close_p. For `anytime_td` the line columns
    are empty and open_p/close_p hold P(TD >= 1)."""
    import polars as pl  # noqa: PLC0415

    out = []
    for g in games_cached(seasons):
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        for r in g["rows"]:
            grouped[(r.get("a"), r.get("tm"), r["t"])].append(r)
        for (ath, tm, stat), items in grouped.items():
            base = {"season": g["season"], "week": g["week"], "game": g["game"], "kickoff": g.get("kickoff"),
                    "home": g.get("home"), "away": g.get("away"), "athlete": ath, "team_id": tm, "stat": stat}
            if stat == "anytime_td":
                po, pc = anytime_prob(items, "o"), anytime_prob(items, "c")
                if po is None and pc is None:
                    continue
                out.append({**base, "open_line": None, "open_p": po, "close_line": None, "close_p": pc})
                continue
            ol, op = main_line(items, "o")
            cl, cp = main_line(items, "c")
            if ol is None and cl is None:
                continue
            out.append({**base, "open_line": ol, "open_p": op, "close_line": cl, "close_p": cp})
    return pl.DataFrame(out, infer_schema_length=None)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="crawl ESPN's pregame player props into .cache/props/")
    ap.add_argument("season", type=int)
    ap.add_argument("--weeks", default="1-18")
    a = ap.parse_args()
    lo, _, hi = a.weeks.partition("-")
    n = crawl(a.season, list(range(int(lo), int(hi or lo) + 1)))
    print(f"props: {n} games added for {a.season}")
