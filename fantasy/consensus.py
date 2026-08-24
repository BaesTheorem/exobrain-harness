#!/usr/bin/env python3
"""Build the independent judging board: draftbot/consensus.json.

This is the fix for the self-grading loop. The drafting board (vor.py) is built
from ESPN projections, Sleeper, and The Ringer; grading rosters on those same
numbers can only ever measure execution, never board error. This file pulls
season projections from sources the bot NEVER drafts on and averages them,
because the projection-accuracy research's one stable finding is that the
average across sources beats any single source.

Sources (both full tables, no auth):
  - CBS Sports season PPR projections (~100 players per position)
  - FFToday season projections, LeagueID=190 = full PPR (verified empirically:
    Gibbs 295.4 std -> 367.4 at 190, exactly +1 per reception; 17 is half PPR)

FIREWALL: consensus.json is the judge's data. vor.py must never read it, and
nothing from here feeds the drafting board. Only settled results from the
disagreement ledger (ledger.py) are allowed to change how the board is built.

Usage:
    python3 fantasy/consensus.py          # writes draftbot/consensus.json
"""

import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "draftbot" / "consensus.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

CBS_POS = ("QB", "RB", "WR", "TE", "K", "DST")
FFT_POS = {"QB": 10, "RB": 20, "WR": 30, "TE": 40, "K": 80, "DST": 99}
# NFL nicknames, for normalizing team-defense names across sources.
NICKS = (
    "Cardinals Falcons Ravens Bills Panthers Bears Bengals Browns Cowboys "
    "Broncos Lions Packers Texans Colts Jaguars Chiefs Raiders Chargers Rams "
    "Dolphins Vikings Patriots Saints Giants Jets Eagles Steelers 49ers "
    "Seahawks Buccaneers Titans Commanders"
).split()


def fetch(url, tries=3):
    # FFToday rate-limits bursts (403 after ~6 rapid hits), so pace politely
    # and back off on refusal rather than dying half-fetched.
    last: Exception = RuntimeError(f"unreachable: {url}")
    for i in range(tries):
        time.sleep(1.5 + 3.0 * i)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("latin-1")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 403:
                raise
    raise last


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def dst_name(raw):
    """'Houston Texans' / 'Texans DST' / 'HOU Texans' -> 'Texans D/ST'."""
    for nick in NICKS:
        if nick.lower() in raw.lower():
            return f"{nick} D/ST"
    return None


def pull_cbs(pos):
    url = f"https://www.cbssports.com/fantasy/football/stats/{pos}/2026/season/projections/ppr/"
    html = fetch(url)
    out = {}
    for row in re.findall(r'<tr class="TableBase-bodyTr">(.*?)</tr>', html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 3:
            continue
        text = [re.sub(r"<[^>]+>|\s+", " ", c).strip() for c in cells]
        # fpts is the second-to-last column on every CBS position page
        # (last is fppg); the player cell is the first.
        try:
            pts = float(text[-2].replace(",", ""))
        except ValueError:
            continue
        if pos == "DST":
            # The DST page renders a logo lockup, not a player cell; the team
            # slug in the href ('/nfl/teams/DEN/denver-broncos/') is the only
            # place the full team name appears in text[0]-stripped form.
            m = re.search(r"/nfl/teams/[A-Z]+/([a-z-]+)/", cells[0])
            name = dst_name(m.group(1).replace("-", " ")) if m else dst_name(text[0])
        else:
            # The long-form cell nests the anchor two spans deep:
            # <span class="CellPlayerName--long"><span><a>Bijan Robinson</a>...
            m = re.search(
                r'CellPlayerName--long.*?<a[^>]*>([^<]+)</a>', cells[0], re.S
            )
            name = m.group(1).strip() if m else None
        if name:
            out[name] = pts
    return out


def pull_fftoday(pos):
    out = {}
    for page in (0, 1):
        url = (
            "https://www.fftoday.com/rankings/playerproj.php"
            f"?Season=2026&PosID={FFT_POS[pos]}&LeagueID=190&cur_page={page}"
        )
        html = fetch(url)
        rows = re.findall(
            r'/stats/players/\d+/[^"]*"[^>]*>([^<]+)</A>(.*?)</TR>', html, re.S
        )
        if not rows and pos == "DST":
            # Team defenses link to team pages, not player pages.
            rows = re.findall(
                r'/stats/[^"]*TeamID[^"]*"[^>]*>([^<]+)</A>(.*?)</TR>', html, re.S
            )
        for name, rest in rows:
            tds = re.findall(r">\s*([\d.,]+)\s*<", rest)
            if not tds:
                continue
            pts = float(tds[-1].replace(",", ""))
            name = name.strip()
            if pos == "DST":
                name = dst_name(name) or name
            out[name] = pts
        if len(rows) < 50:
            break
    return out


def main():
    board = {}
    counts = {}
    for pos in CBS_POS:
        srcs = {}
        for label, puller in (("cbs", pull_cbs), ("fft", pull_fftoday)):
            try:
                srcs[label] = puller(pos)
            except Exception as exc:  # noqa: BLE001 -- a judge missing one source should degrade, not die
                print(f"WARN {label} {pos}: {exc}", file=sys.stderr)
                srcs[label] = {}
        merged = {}
        for label, players in srcs.items():
            for name, pts in players.items():
                key = norm(name)
                rec = merged.setdefault(
                    key, {"name": name, "pos": "D/ST" if pos == "DST" else pos}
                )
                rec[label] = pts
        for key, rec in merged.items():
            vals = [rec[s] for s in ("cbs", "fft") if s in rec]
            rec["pts"] = round(sum(vals) / len(vals), 1)
            board[key] = rec
        counts[pos] = (
            f"{len(merged)} "
            f"(cbs {len(srcs['cbs'])}, fft {len(srcs['fft'])})"
        )

    OUT.write_text(json.dumps(board))
    for pos, line in counts.items():
        print(f"{pos:<4} {line}")
    both = sum(1 for r in board.values() if "cbs" in r and "fft" in r)
    print(f"total {len(board)}, averaged from both sources: {both}")


if __name__ == "__main__":
    main()
