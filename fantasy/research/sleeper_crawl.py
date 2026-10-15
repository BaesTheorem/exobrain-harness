#!/usr/bin/env python3
"""Resumable snowball crawler for completed Sleeper redraft leagues.

Feeds standings_decomp.py, which splits a fantasy team's season into draft
value, in-season acquisitions, lineup decisions and schedule luck. This script
only collects. It starts from one or more public seed leagues, reads each
league's members from its rosters, lists every league those members played in
2024 and 2025 (GET /user/<id>/leagues/nfl/<season>), keeps the leagues that
pass the filters below, and downloads each kept league in full.

Filters, applied to the league object before any download (cheap):
  settings.type == 0 (redraft), not best ball, status "complete",
  10 to 14 rosters, scoring_settings.rec == 1 (full PPR),
  no median matchup (league_average_match 0 or absent),
  playoff_week_start 14 or 15 with start_week 1 (13- or 14-week season),
  roster slots limited to QB RB WR TE K DEF FLEX SUPER_FLEX REC_FLEX
  WRRB_FLEX BN (IDP leagues are dropped).
Then, after download (full): a completed draft that gave every roster at
least as many picks as it has starting slots, a matchup entry for every
roster in every regular week, games in pairs, matchup points equal to the sum
of starters_points within 0.02, no commissioner point overrides, and real
play (median team-week score above 40, under 3% of starting slots empty).

Raw data goes to --out (default /tmp/ffvoi), one gzip JSON per kept league,
plus the weekly all-player stats, the player table, and state.json.gz. The
files hold other people's league data. They stay outside the repo.

    python3 sleeper_crawl.py --seed-league <id> [--target 1000] [--rate 7.4]
    python3 sleeper_crawl.py            # resume from state.json.gz

INVARIANTS
- Never more than --rate requests per second (default 7.4; Sleeper asks for
  under 1000 a minute). One thread, one session, a minimum gap between starts.
- Resumable: state is written atomically after every league, and a league
  file is written only after every payload for it arrived.
- Stops when --target leagues are kept (default 1000).
- Writes nothing inside the repo.
"""

import argparse
import gzip
import json
import os
import pathlib
import signal
import sys
import time

import requests

API = "https://api.sleeper.app/v1"
SEASONS = (2024, 2025)
SLOTS_OK = {"QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "SUPER_FLEX",
            "REC_FLEX", "WRRB_FLEX", "BN"}
KEEP_KEYS = ("league_id", "season", "status", "settings", "scoring_settings",
             "roster_positions", "total_rosters", "draft_id", "previous_league_id")
STOP = False


def on_signal(_sig, _frame):
    global STOP
    STOP = True


class Client:
    def __init__(self, rate):
        self.gap = 1.0 / rate
        self.last = 0.0
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "ffvoi-research/1.0"
        self.n = 0

    def get(self, path):
        url = path if path.startswith("http") else API + path
        for attempt in range(6):
            wait = self.last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.n += 1
            try:
                r = self.s.get(url, timeout=30)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            time.sleep(min(60, 2 ** (attempt + 1)))  # 429 / 5xx
        raise RuntimeError(f"failed after retries: {url}")


def dump_gz(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def load_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def cheap_reject(lg):
    """Reason string if the league object fails a filter, else None."""
    st = lg.get("settings") or {}
    sc = lg.get("scoring_settings") or {}
    if lg.get("status") != "complete":
        return "status"
    if st.get("type") != 0:
        return "not_redraft"
    if st.get("best_ball"):
        return "best_ball"
    n = lg.get("total_rosters") or 0
    if not 10 <= n <= 14:
        return "size"
    if sc.get("rec") != 1:
        return "not_full_ppr"
    if st.get("league_average_match") not in (0, None):
        return "median"
    if st.get("playoff_week_start") not in (14, 15):
        return "season_length"
    if st.get("start_week") not in (1, None):
        return "start_week"
    if not set(lg.get("roster_positions") or []) <= SLOTS_OK:
        return "slots"
    return None


def full_reject(lg, rosters, picks, matchups):
    """Reason string if the downloaded league fails a filter, else None."""
    n = lg["total_rosters"]
    if not rosters or len(rosters) != n:
        return "rosters"
    starters = [p for p in lg["roster_positions"] if p != "BN"]
    per_roster = {}
    for p in picks or []:
        per_roster[p.get("roster_id")] = per_roster.get(p.get("roster_id"), 0) + 1
    rids = {r["roster_id"] for r in rosters}
    if any(per_roster.get(r, 0) < len(starters) for r in rids):
        return "draft"
    scores, empty, slots = [], 0, 0
    for wk, ms in matchups.items():
        if not ms or len(ms) != n:
            return f"matchups_w{wk}"
        games = {}
        for m in ms:
            if m.get("custom_points") is not None:
                return "custom_points"
            if m.get("roster_id") not in rids:
                return "roster_id"
            mid = m.get("matchup_id")
            games.setdefault(mid, []).append(m)
            sp = m.get("starters_points") or []
            if abs(sum(sp) - (m.get("points") or 0)) > 0.02:
                return "points_mismatch"
            empty += sum(1 for s in m.get("starters") or [] if s in ("0", None))
            slots += len(starters)
            scores.append(m.get("points") or 0)
        byes = games.pop(None, [])
        if len(byes) != n % 2 or any(len(g) != 2 for g in games.values()):
            return "pairing"
    scores.sort()
    if scores[len(scores) // 2] <= 40:
        return "not_played"
    if empty > 0.03 * slots:
        return "empty_slots"
    return None


def fetch_league(c, lg):
    lid = lg["league_id"]
    weeks = range(1, lg["settings"]["playoff_week_start"])
    rosters = c.get(f"/league/{lid}/rosters")
    drafts = c.get(f"/league/{lid}/drafts") or []
    done = [d for d in drafts if d.get("status") == "complete"]
    if not done:
        return None, "no_draft", rosters
    picks = c.get(f"/draft/{done[0]['draft_id']}/picks")
    matchups = {}
    for wk in weeks:
        matchups[str(wk)] = c.get(f"/league/{lid}/matchups/{wk}")
        if not matchups[str(wk)]:
            return None, f"matchups_w{wk}", rosters
    why = full_reject(lg, rosters, picks, matchups)
    if why:
        return None, why, rosters
    tx = {str(wk): c.get(f"/league/{lid}/transactions/{wk}") or [] for wk in weeks}
    wb = c.get(f"/league/{lid}/winners_bracket")
    return {"league": lg, "rosters": rosters, "drafts": drafts,
            "draft": done[0], "picks": picks, "matchups": matchups,
            "transactions": tx, "winners_bracket": wb,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, None, rosters


def owners(rosters):
    out = []
    for r in rosters or []:
        if r.get("owner_id"):
            out.append(r["owner_id"])
        out.extend(r.get("co_owners") or [])
    return out


def ensure_static(c, out):
    """Weekly all-player stats for weeks 1-14 of each season, and the player table."""
    sdir = out / "stats"
    sdir.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        for wk in range(1, 15):
            p = sdir / f"{season}_{wk:02d}.json.gz"
            if not p.exists():
                dump_gz(p, c.get(f"{API}/stats/nfl/regular/{season}/{wk}"))
    p = out / "players_nfl.json.gz"
    if not p.exists():
        dump_gz(p, c.get("/players/nfl"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/ffvoi")
    ap.add_argument("--seed-league", action="append", default=[])
    ap.add_argument("--target", type=int, default=1000)
    ap.add_argument("--rate", type=float, default=7.4)
    ap.add_argument("--max-minutes", type=float, default=150)
    a = ap.parse_args()
    if a.rate > 8:
        sys.exit("rate must stay under 8 requests per second")
    out = pathlib.Path(a.out)
    (out / "leagues").mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    c = Client(a.rate)
    ensure_static(c, out)

    sp = out / "state.json.gz"
    if sp.exists():
        st = load_gz(sp)
    else:
        st = {"user_queue": [], "users_seen": [], "cand_queue": [],
              "leagues_seen": [], "kept": {}, "rejected": {}, "funnel": {},
              "n_requests": 0}
    users_seen, leagues_seen = set(st["users_seen"]), set(st["leagues_seen"])
    for lid in a.seed_league:
        lg = c.get(f"/league/{lid}")
        for u in owners(c.get(f"/league/{lid}/rosters")):
            if u not in users_seen:
                users_seen.add(u)
                st["user_queue"].append(u)
        if lg:
            leagues_seen.add(lid)

    def save():
        st["users_seen"], st["leagues_seen"] = sorted(users_seen), sorted(leagues_seen)
        st["n_requests"] = st.get("n_requests", 0) + c.n
        c.n = 0
        dump_gz(sp, st)

    t0 = time.monotonic()
    while len(st["kept"]) < a.target and not STOP:
        if time.monotonic() - t0 > a.max_minutes * 60:
            break
        if st["cand_queue"]:
            lg = st["cand_queue"].pop(0)
            lid = lg["league_id"]
            data, why, rosters = fetch_league(c, lg)
            for u in owners(rosters):
                if u not in users_seen:
                    users_seen.add(u)
                    st["user_queue"].append(u)
            if data is None:
                st["rejected"][lid] = why
                key = "full:" + (why.split("_w")[0] if why else "?")
                st["funnel"][key] = st["funnel"].get(key, 0) + 1
            else:
                dump_gz(out / "leagues" / f"{lid}.json.gz", data)
                s = lg["settings"]
                st["kept"][lid] = {"season": int(lg["season"]),
                                   "teams": lg["total_rosters"],
                                   "waiver_type": s.get("waiver_type")}
                st["funnel"]["kept"] = st["funnel"].get("kept", 0) + 1
            save()
            k = len(st["kept"])
            if k % 10 == 0 and data is not None:
                print(time.strftime("%H:%M:%S"), "kept", k, "rejected",
                      len(st["rejected"]), "queue", len(st["cand_queue"]),
                      "users", len(st["user_queue"]), flush=True)
        elif st["user_queue"]:
            u = st["user_queue"].pop(0)
            for season in SEASONS:
                for lg in c.get(f"/user/{u}/leagues/nfl/{season}") or []:
                    lid = lg.get("league_id")
                    if not lid or lid in leagues_seen:
                        continue
                    leagues_seen.add(lid)
                    why = cheap_reject(lg)
                    key = "cheap:" + (why or "pass")
                    st["funnel"][key] = st["funnel"].get(key, 0) + 1
                    if why is None:
                        st["cand_queue"].append({k: lg.get(k) for k in KEEP_KEYS})
        else:
            print("frontier exhausted", flush=True)
            break
    save()
    print("done: kept", len(st["kept"]), "requests", st["n_requests"],
          "funnel", json.dumps(st["funnel"], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
