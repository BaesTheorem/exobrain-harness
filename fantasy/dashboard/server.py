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


def pull() -> dict:
    m = espn("matchup")
    sb = espn("scoreboard")
    frac = m.get("in_progress") or {}
    season = json.loads(SEASON.read_text()) if SEASON.exists() else None
    w = m["win"]
    st = {"ok": True, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
          "week": m["week"], "live": bool(frac), "frac": frac, "win": w, "rule": m.get("rule"),
          "margin_source": m.get("margin_source"),
          "me": {"team_id": m["me"]["team_id"], "team": m["me"]["team"], "actual": m["me"]["actual"], "rows": starters(m["me"], frac)},
          "opp": {"team_id": m["opp"]["team_id"], "team": m["opp"]["team"], "actual": m["opp"]["actual"], "rows": starters(m["opp"], frac)},
          "games": [{"hid": g["home"]["team_id"], "aid": g["away"]["team_id"], "h": g["home"]["team"], "a": g["away"]["team"], "hs": g["home"]["actual"],
                     "as": g["away"]["actual"], "p": g["model"]["p_home"],
                     "mine": g["home"]["mine"] or g["away"]["mine"]} for g in sb["matchups"]],
          "season": season}
    LOG.mkdir(exist_ok=True)
    path = LOG / f"{datetime.now().year}-w{m['week']:02d}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({"t": st["at"], "p": w["p"], "mu_me": w["mu_me"], "mu_opp": w["mu_opp"],
                            "me": m["me"]["actual"], "opp": m["opp"]["actual"], "live": st["live"]}) + "\n")
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
    api = Espn()
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
