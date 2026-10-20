"""Live week dashboard: serves index.html and /api/state, and logs P(win).

Every POLL seconds while a game is on (IDLE otherwise) it runs `espn matchup`
and `espn scoreboard` (the lineup model, same numbers as `espn check`) and
appends one line to log/<season>-w<week>.jsonl. That log is the win
probability line; nothing else records P(win) over time.

INVARIANTS
- Read-only: it calls the read-only `espn` CLI and never `espn-tx`.
- The page reads only /api/state; all model numbers come from `espn`, never
  recomputed here, so the page and `espn check` cannot disagree.
"""

import json
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
ESPN = FANTASY / "bin" / "espn"
SEASON = FANTASY / "draftbot" / "season_sim_latest.json"
LOG = HERE / "log"
PORT = 5023
POLL, IDLE = 60, 600
FAST = 10  # live scores: one light league call, so the score bug matches the ESPN app

sys.path.insert(0, str(FANTASY))
from espncli.client import Espn  # noqa: E402

live_scores: dict = {}
CACHE = HERE / "cache"
ATHLETE = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{}"
api_lock = threading.Lock()
_api: Espn | None = None
_logos: dict[int, str] = {}
_names: dict[str, int] = {}
_logos_at = 0.0


def get_api() -> Espn:
    global _api
    with api_lock:
        if _api is None:
            _api = Espn()
        return _api


def team_logos() -> dict[str, int]:
    """Team name -> id, refreshing the logo URLs once an hour (mTeam)."""
    global _logos_at
    if time.time() - _logos_at > 3600:
        d = get_api().league("mTeam")
        for t in d.get("teams", []):
            _logos[t["id"]] = t.get("logo") or ""
            _names[(t.get("name") or "").strip()] = t["id"]
        _logos_at = time.time()
    return dict(_names)


def logo_bytes(team_id: int) -> tuple[bytes, str] | None:
    """The team picture, cached on disk for a day. Custom uploads on ESPN's
    image host need the league cookies, so the page cannot load them itself."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"logo-{team_id}"
    meta = CACHE / f"logo-{team_id}.type"
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return path.read_bytes(), meta.read_text() if meta.exists() else "image/png"
    url = _logos.get(team_id)
    if not url:
        return None
    api = get_api()
    headers = {"User-Agent": "Mozilla/5.0", **(api._auth() if "fantasy.espn.com" in url else {})}  # noqa: SLF001 - same package
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        body, ctype = r.read(), r.headers.get("Content-Type") or "image/png"
    if ctype == "image/jpg":
        ctype = "image/jpeg"
    path.write_bytes(body)
    meta.write_text(ctype)
    return body, ctype


def jerseys(ids: list[int]) -> dict[int, str | None]:
    """Jersey numbers from ESPN's public athlete API (the fantasy API has none),
    cached for a week per player. D/ST entries have no athlete and stay None."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "jerseys.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    now, changed = time.time(), False
    for pid in ids:
        hit = cache.get(str(pid))
        if hit and now - hit["at"] < 7 * 86400:
            continue
        num = None
        if pid > 0:
            try:
                req = urllib.request.Request(ATHLETE.format(pid), headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    num = json.load(r).get("athlete", {}).get("jersey")
            except Exception:  # noqa: BLE001 - a missing number is cosmetic
                num = None
        cache[str(pid)] = {"n": num, "at": now}
        changed = True
    if changed:
        path.write_text(json.dumps(cache))
    return {pid: cache[str(pid)]["n"] for pid in ids}

state: dict = {"ok": False, "error": "first pull pending"}
lock = threading.Lock()


def espn(*args: str) -> dict:
    out = subprocess.run([sys.executable, str(ESPN), *args, "--json", "--no-pending"],
                         capture_output=True, text=True, timeout=120, cwd=FANTASY)
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[-300:] or f"espn {args[0]} exit {out.returncode}")
    return json.loads(out.stdout)


def starters(side: dict, frac: dict[str, float]) -> list[dict]:
    rows = []
    for r in side["rows"]:
        if r["slot"] in ("BE", "IR"):
            continue
        proj = r.get("proj") or 0.0
        if r["team"] in frac:
            rem, st = proj * frac[r["team"]], "live"
        elif not r["locked"]:
            rem, st = proj, "upcoming"
        else:
            rem, st = 0.0, "final"
        rows.append({"id": r["id"], "slot": r["slot"], "name": r["name"], "team": r["team"], "opp": r["opp"],
                     "kick": r["kick"], "bank": r["actual"] or 0.0, "rem": round(rem, 1), "state": st,
                     "status": r.get("status") or "", "left": frac.get(r["team"])})
    return rows


def view(m: dict, frac: dict[str, float]) -> dict:
    side = lambda x: {"team_id": x["team_id"], "team": x["team"], "actual": x["actual"],  # noqa: E731
                      "rows": starters(x, frac)}
    return {"id": m["matchup_id"], "win": m["win"], "me": side(m["me"]), "opp": side(m["opp"])}


def pull() -> dict:
    sb = espn("scoreboard")
    mine_id = next(g["id"] for g in sb["matchups"] if g["home"]["mine"] or g["away"]["mine"])
    # One `espn matchup` per game, in parallel (about 2 s each). Ours is read
    # from our side; every other game from the home side.
    jobs = {g["id"]: (["matchup"] if g["id"] == mine_id else ["matchup", "--team", str(g["home"]["team_id"])])
            for g in sb["matchups"]}
    with ThreadPoolExecutor(max_workers=6) as ex:
        got = dict(zip(jobs, ex.map(lambda a: espn(*a), jobs.values())))
    m = got[mine_id]
    frac = m.get("in_progress") or {}
    views = {mid: view(x, frac) for mid, x in got.items()}
    season = json.loads(SEASON.read_text()) if SEASON.exists() else None
    st = {"ok": True, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
          "week": m["week"], "live": bool(frac), "frac": frac, "mine": mine_id, "views": views,
          "games": [{"id": g["id"], "hid": g["home"]["team_id"], "aid": g["away"]["team_id"],
                     "h": g["home"]["team"], "a": g["away"]["team"], "hs": g["home"]["actual"],
                     "as": g["away"]["actual"], "p": g["model"]["p_home"],
                     "mine": g["id"] == mine_id} for g in sb["matchups"]],
          "season": season}
    try:
        st["team_ids"] = team_logos()
    except Exception:  # noqa: BLE001 - pictures are cosmetic
        st["team_ids"] = dict(_names)
    try:
        nums = jerseys([r["id"] for v in views.values() for k in ("me", "opp") for r in v[k]["rows"]])
        for v in views.values():
            for k in ("me", "opp"):
                for r in v[k]["rows"]:
                    r["jersey"] = nums.get(r["id"])
    except Exception:  # noqa: BLE001
        pass
    LOG.mkdir(exist_ok=True)
    path = LOG / f"{datetime.now().year}-w{m['week']:02d}.jsonl"
    w = m["win"]
    with path.open("a") as f:
        f.write(json.dumps({"t": st["at"], "p": w["p"], "mu_me": w["mu_me"], "mu_opp": w["mu_opp"],
                            "me": m["me"]["actual"], "opp": m["opp"]["actual"], "live": st["live"],
                            "all": {str(k): {"p": v["win"]["p"], "me": v["me"]["actual"], "opp": v["opp"]["actual"]}
                                    for k, v in views.items()}}) + "\n")
    st["history"] = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return st


def loop() -> None:
    global state
    while True:
        try:
            new = pull()
            with lock:
                state = new
            wait = POLL if new["live"] else IDLE
        except Exception as e:  # noqa: BLE001 - a failed pull keeps the last good state on screen
            with lock:
                state = {**state, "error": f"{datetime.now():%H:%M} {e}"}
            wait = POLL
        time.sleep(wait)


def fast_loop() -> None:
    """Team and starter points straight from ESPN's live matchup score, every
    FAST seconds while a game is on. The win model stays on the 60 s pull; the
    page shifts its means by the points scored since that pull."""
    global live_scores
    api = get_api()
    while True:
        week = state.get("week")
        t0 = time.monotonic()
        if week:
            try:
                d = api.league("mMatchupScore", "mScoreboard", period=week)
                teams, players = {}, {}
                for m in d.get("schedule", []):
                    if m.get("matchupPeriodId") != week:
                        continue
                    for k in ("home", "away"):
                        side = m.get(k)
                        if not side:
                            continue
                        teams[side["teamId"]] = side.get("totalPointsLive", side.get("totalPoints"))
                        for e in (side.get("rosterForCurrentScoringPeriod") or {}).get("entries", []):
                            pe = e["playerPoolEntry"]
                            players[pe["id"]] = pe.get("appliedStatTotal")
                with lock:
                    live_scores = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
                                   "teams": teams, "players": players}
            except Exception as e:  # noqa: BLE001 - the 60 s pull still carries the scores
                with lock:
                    live_scores = {**live_scores, "error": str(e)[:200]}
        gap = 2 if not week else FAST if state.get("live") else POLL
        time.sleep(max(1.0, gap - (time.monotonic() - t0)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if self.path.startswith("/api/live"):
            with lock:
                body, ctype = json.dumps(live_scores).encode(), "application/json"
        elif self.path.startswith("/api/state"):
            with lock:
                body, ctype = json.dumps(state).encode(), "application/json"
        elif self.path.startswith("/logo/"):
            try:
                got = logo_bytes(int(self.path.split("/")[2]))
            except Exception:  # noqa: BLE001
                got = None
            if not got:
                self.send_error(404)
                return
            body, ctype = got
        elif self.path in ("/", "/index.html"):
            body, ctype = (HERE / "index.html").read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        # The Console previews HTML in a sandbox (Origin: null); allow it to read the state.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=fast_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
