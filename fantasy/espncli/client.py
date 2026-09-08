"""Read-only ESPN access shared by the `espn` CLI.

The fantasy league API is the same one `bin/ff` reads, reached with the
session cookies in the gitignored fantasy/espn-credentials.json. The public
NFL API needs no cookies and never gets them.

INVARIANTS:
- Read-only. Every request is a GET. No lineup, claim, trade, or draft pick
  is ever sent from here; writes belong in a separately named tool with its
  own confirmation gate (the draftbot is the only one that exists).
- Credentials come only from the gitignored JSON. Never printed, never
  logged, never sent anywhere but lm-api-reads.fantasy.espn.com.
- Host choice is deliberate: site.api.espn.com answers 403 to non-browser
  clients through Akamai (checked 2026-09-07); site.web.api.espn.com serves
  the same routes and does not.
- Player lookups by id use the kona_playercard view. kona_player_info ignores
  filterIds and returns 400 for it (checked 2026-09-07), and the /players
  path ignores the filter and returns the whole pool.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FANTASY_DIR = Path(__file__).resolve().parent.parent
CREDS = FANTASY_DIR / "espn-credentials.json"
CACHE_DIR = FANTASY_DIR / ".cache"
CACHE_TTL = 24 * 3600

READS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
PUBLIC = "https://site.web.api.espn.com/apis"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
TZ = ZoneInfo("America/Chicago")

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K",
        20: "BE", 21: "IR", 23: "FLEX"}
SLOT_BY_NAME = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "K": 17, "DST": 16,
                "D/ST": 16, "FLEX": 23}
BENCH, IR = 20, 21
STARTER_SLOTS = [0, 2, 4, 6, 23, 16, 17]  # display order
INACTIVE = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}
STAT_SEASON, STAT_WEEK = 0, 1
SRC_ACTUAL, SRC_PROJ = 0, 1


class EspnError(SystemExit):
    """A user-facing failure: exit nonzero with the message, no traceback."""


def load_creds() -> dict[str, Any]:
    if not CREDS.exists():
        raise EspnError(
            "No credentials at fantasy/espn-credentials.json. Run `ff refresh` "
            "to pull them from Chrome, or see fantasy/README.md.")
    c = json.loads(CREDS.read_text())
    for k in ("league_id", "season", "espn_s2", "SWID"):
        if not c.get(k):
            raise EspnError(f"Credential file is missing '{k}'. See fantasy/README.md.")
    return c


def norm(name: str) -> str:
    """Fold a player name for matching: no accents, punctuation, suffixes, case."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    return " ".join(s.split())


def stat_value(player: dict, season: int, period: int, source: int, split: int) -> float | None:
    """One entry from a player's stats list, matched on all four keys.

    seasonId matters: a D/ST carries a (0, proj, season) row for both 2025
    and 2026, and only the seasonId tells them apart.
    """
    for s in player.get("stats") or []:
        if (s.get("seasonId") == season and s.get("scoringPeriodId") == period
                and s.get("statSourceId") == source and s.get("statSplitTypeId") == split):
            return s.get("appliedTotal")
    return None


def week_proj(player: dict, season: int, week: int) -> float | None:
    return stat_value(player, season, week, SRC_PROJ, STAT_WEEK)


def week_actual(player: dict, season: int, week: int) -> float | None:
    return stat_value(player, season, week, SRC_ACTUAL, STAT_WEEK)


def season_proj(player: dict, season: int) -> float | None:
    return stat_value(player, season, 0, SRC_PROJ, STAT_SEASON)


def season_actual(player: dict, season: int) -> float | None:
    return stat_value(player, season, 0, SRC_ACTUAL, STAT_SEASON)


def local(ms: int | float | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(TZ)


def team_name(t: dict) -> str:
    n = (t.get("name") or "").strip()
    if n:
        return n
    return f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {t['id']}"


def initials(member: dict | None) -> str:
    """Owner shown as initials only. League members are other people; their
    names stay out of terminal output, logs, and anything that might be pasted."""
    if not member:
        return "?"
    parts = [member.get("firstName") or "", member.get("lastName") or ""]
    out = "".join(p[0].upper() + "." for p in parts if p)
    return out or (member.get("displayName") or "?")[:1].upper() + "."


class Espn:
    """One league, one season, read-only."""

    def __init__(self, creds: dict[str, Any] | None = None, fresh: bool = False):
        self.creds = creds or load_creds()
        self.season = int(self.creds["season"])
        self.league_id = int(self.creds["league_id"])
        self.fresh = fresh
        self._pro: dict[int, dict] | None = None
        self._index: list[dict] | None = None

    # ---- transport -------------------------------------------------------

    def _get(self, url: str, headers: dict[str, str] | None = None, timeout: int = 60,
             retries: int = 1) -> Any:
        h = {"User-Agent": UA, "Accept": "application/json"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (http.client.IncompleteRead, ConnectionResetError, TimeoutError, socket.timeout) as e:
            # The public injury report is ~9 MB and ESPN's edge sometimes cuts
            # it off mid-body; one retry recovers it (2026-09-07).
            if retries > 0:
                return self._get(url, headers, timeout, retries - 1)
            raise EspnError(f"ESPN cut the response short for {url.split('?')[0]}: {e}") from None
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            if e.code in (401, 403) and "fantasy.espn.com" in url and "lm-api" in url:
                raise EspnError(
                    "ESPN rejected the cookies (auth expired). Run `ff refresh` "
                    "to re-pull them from Chrome while logged into ESPN.") from None
            raise EspnError(f"ESPN HTTP {e.code} for {url.split('?')[0]}: {body}") from None
        except urllib.error.URLError as e:
            raise EspnError(f"Network error reaching ESPN: {e.reason}") from None

    def _auth(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Cookie": f"espn_s2={self.creds['espn_s2']}; SWID={self.creds['SWID']}"}
        if extra:
            h.update(extra)
        return h

    def league_url(self, path: str = "") -> str:
        return (f"{READS}/seasons/{self.season}/segments/0/leagues/"
                f"{self.league_id}{path}")

    def league(self, *views: str, period: int | None = None,
               filt: dict | None = None, path: str = "") -> Any:
        """GET the league with the given views (and X-Fantasy-Filter, if any)."""
        q = [("view", v) for v in views]
        if period is not None:
            q.append(("scoringPeriodId", str(period)))
        url = self.league_url(path) + ("?" + urllib.parse.urlencode(q) if q else "")
        extra = {"X-Fantasy-Filter": json.dumps(filt)} if filt else None
        return self._get(url, self._auth(extra))

    def season_view(self, view: str) -> Any:
        return self._get(f"{READS}/seasons/{self.season}?view={view}", self._auth())

    def public(self, path: str, **params: Any) -> Any:
        """GET the cookie-free public API (scoreboard, injuries, news)."""
        url = f"{PUBLIC}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return self._get(url)

    def injuries(self) -> Any:
        """The league-wide injury report, ~9 MB, so it is cached for 30 minutes."""
        url = f"{PUBLIC}/site/v2/sports/football/nfl/injuries"
        return self._cached("injuries", lambda: self._get(url, timeout=120, retries=4), ttl=1800)

    # ---- caches ----------------------------------------------------------

    def _cached(self, name: str, build, ttl: int = CACHE_TTL) -> Any:
        CACHE_DIR.mkdir(exist_ok=True)
        f = CACHE_DIR / f"{name}-{self.season}.json"
        if not self.fresh and f.exists() and time.time() - f.stat().st_mtime < ttl:
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                pass
        data = build()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, f)
        return data

    def pro_teams(self) -> dict[int, dict]:
        """NFL teams keyed by ESPN pro team id: abbrev, name, bye, games by week."""
        if self._pro is None:
            def build():
                d = self.season_view("proTeamSchedules_wl")
                out = {}
                for t in d.get("settings", {}).get("proTeams", []):
                    out[str(t["id"])] = {
                        "id": t["id"], "abbrev": (t.get("abbrev") or "").upper(),
                        "name": f"{t.get('location', '')} {t.get('name', '')}".strip(),
                        "bye": t.get("byeWeek") or 0,
                        "games": t.get("proGamesByScoringPeriod") or {},
                    }
                return out
            raw = self._cached("proteams", build)
            self._pro = {int(k): v for k, v in raw.items()}
        return self._pro

    def pro(self, team_id: int | None) -> dict:
        return self.pro_teams().get(team_id or 0, {"abbrev": "FA", "name": "Free agent", "bye": 0, "games": {}})

    def game(self, team_id: int | None, week: int) -> dict | None:
        """The NFL game a pro team plays in a scoring period, or None on a bye."""
        games = self.pro(team_id).get("games", {}).get(str(week)) or []
        return games[0] if games else None

    def opponent(self, team_id: int | None, week: int) -> str:
        """'KC', '@KC', or 'BYE' for the given week."""
        g = self.game(team_id, week)
        if not g:
            return "BYE"
        if g.get("homeProTeamId") == team_id:
            return self.pro(g.get("awayProTeamId")).get("abbrev", "?")
        return "@" + self.pro(g.get("homeProTeamId")).get("abbrev", "?")

    def kickoff(self, team_id: int | None, week: int) -> datetime | None:
        g = self.game(team_id, week)
        return local(g.get("date")) if g else None

    def players_index(self) -> list[dict]:
        """Every active player: id, name, pos, pro team. Public data, cached a day."""
        if self._index is None:
            def build():
                raw = self._get(
                    f"{READS}/seasons/{self.season}/players?scoringPeriodId=0&view=players_wl",
                    self._auth({"X-Fantasy-Filter": json.dumps({"filterActive": {"value": True}})}))
                return [{"id": p["id"], "name": p.get("fullName") or "",
                         "pos": POS.get(p.get("defaultPositionId"), ""),
                         "team": p.get("proTeamId") or 0}
                        for p in raw if p.get("fullName")]
            self._index = self._cached("players", build)
        assert self._index is not None
        return self._index

    def find_players(self, query: str) -> list[dict]:
        """Best matches for a name: exact fold, then prefix, then substring.
        Fantasy positions first so 'Allen' finds Josh before an OT."""
        q = norm(query)
        if not q:
            return []
        exact, prefix, sub = [], [], []
        for p in self.players_index():
            n = norm(p["name"])
            if n == q:
                exact.append(p)
            elif n.startswith(q) or n.endswith(" " + q):
                prefix.append(p)
            elif q in n:
                sub.append(p)
        rank = lambda p: (0 if p["pos"] else 1, p["name"])
        return sorted(exact, key=rank) + sorted(prefix, key=rank) + sorted(sub, key=rank)

    def resolve_one(self, query: str) -> dict:
        """One player or a clear error listing the candidates."""
        if query.isdigit():
            hits = [p for p in self.players_index() if p["id"] == int(query)]
        else:
            hits = self.find_players(query)
        if not hits:
            raise EspnError(f"No active player matches '{query}'.")
        top = [p for p in hits if norm(p["name"]) == norm(query)] or hits
        fantasy = [p for p in top if p["pos"]]
        if len(fantasy) == 1:
            return fantasy[0]
        if len(top) == 1:
            return top[0]
        lines = "\n".join(f"  {p['id']:>8}  {p['name']:<26} {p['pos'] or '-':<5} "
                          f"{self.pro(p['team'])['abbrev']}" for p in top[:12])
        raise EspnError(f"'{query}' is ambiguous. Pass an id instead:\n{lines}")

    # ---- players ---------------------------------------------------------

    def pool(self, filt: dict, period: int | None = None) -> list[dict]:
        """kona_player_info entries under an X-Fantasy-Filter."""
        d = self.league("kona_player_info", period=period, filt={"players": filt})
        return d.get("players", [])

    def player_cards(self, ids: list[int], period: int | None = None) -> list[dict]:
        """Full player cards (weekly stat rows, ownership, injury) for ids."""
        if not ids:
            return []
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            d = self.league("kona_playercard", period=period,
                            filt={"players": {"filterIds": {"value": chunk},
                                              "filterStatsForTopScoringPeriodIds": {
                                                  "value": 17,
                                                  "additionalValue": [f"00{self.season}", f"10{self.season}",
                                                                      f"00{self.season - 1}",
                                                                      f"11{self.season}{period or 1}",
                                                                      f"02{self.season}"]}}})
            out.extend(d.get("players", []))
        return out

    def names_for(self, ids: list[int]) -> dict[int, str]:
        """id -> name via the index, falling back to a card fetch for misses
        (retired players in an old transaction, D/STs by negative id)."""
        want = {int(i) for i in ids if i is not None}
        have = {p["id"]: p["name"] for p in self.players_index() if p["id"] in want}
        miss = sorted(want - set(have))
        for e in self.player_cards(miss):
            have[e["id"]] = e.get("player", {}).get("fullName") or f"player {e['id']}"
        return have

    # ---- league helpers --------------------------------------------------

    def my_team_id(self, data: dict) -> int | None:
        """Pinned team_id first, then the SWID's own team (see ff for why)."""
        pinned = self.creds.get("team_id")
        teams = data.get("teams", [])
        if pinned is not None and any(t["id"] == pinned for t in teams):
            return int(pinned)
        swid = self.creds["SWID"]
        owned = [t["id"] for t in teams if swid in (t.get("owners") or [])]
        if len(owned) == 1:
            return owned[0]
        if len(owned) > 1:
            raise EspnError(f"SWID owns multiple teams {owned}; set team_id in the credential file.")
        return None

    def resolve_team(self, data: dict, who: str | None) -> dict:
        """A team by id, abbrev, or name fragment; default is Alex's."""
        teams = data.get("teams", [])
        if who is None or who.lower() in ("me", "mine"):
            tid = self.my_team_id(data)
            for t in teams:
                if t["id"] == tid:
                    return t
            raise EspnError("Could not identify your team from the credentials.")
        if who.isdigit():
            for t in teams:
                if t["id"] == int(who):
                    return t
        w = who.lower()
        hits = [t for t in teams if (t.get("abbrev") or "").lower() == w]
        hits = hits or [t for t in teams if w in team_name(t).lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise EspnError(f"No team matches '{who}'. Try `espn teams`.")
        raise EspnError(f"'{who}' matches {[team_name(t) for t in hits]}; be more specific.")

    @staticmethod
    def current_week(data: dict) -> int:
        """The scoring period ESPN is on. 0 in the preseason, so floor at 1."""
        wk = int(data.get("scoringPeriodId") or 0)
        if wk < 1:
            wk = int((data.get("status") or {}).get("currentMatchupPeriod") or 1)
        final = int((data.get("status") or {}).get("finalScoringPeriod") or 17)
        return max(1, min(wk, final))

    @staticmethod
    def starters(entries: list[dict]) -> list[dict]:
        return [e for e in entries if e.get("lineupSlotId") not in (BENCH, IR)]

    @staticmethod
    def roster_entries(data: dict, team_id: int) -> list[dict]:
        for t in data.get("teams", []):
            if t["id"] == team_id:
                return (t.get("roster") or {}).get("entries", [])
        return []


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)
