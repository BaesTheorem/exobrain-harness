#!/usr/bin/env python3
"""The opportunity overlay: 2025 volume metrics + TD-regression flags.

The playbook's actual edge (skill §2): opportunity repeats, efficiency does
not, and touchdowns are close to pure noise (last-year TDs -> next-year TDs
R² = 0.079). So the draft sheet should show volume, and flag the two
mispricings a casual room reliably makes:

  BUY   heavy volume, TD-shorted. The market prices him off a fantasy-points
        total that TD luck dragged down; the volume says the points come back.
  SELL  TD-inflated on modest volume. The market prices the touchdowns, which
        do not repeat.

Data: nflreadpy weekly player stats + snap counts, 2025 regular season.
Output: draftbot/opportunity.json (gitignored derived data), consumed by
tier_sheet.py as sheet flags, and a printed report cross-referenced against
the current board. Advisory for Alex and the sign-off process only: the bot
does not read this (a BUY is a *thesis candidate* for signoff.py keep, not an
automatic board change).

Usage:
    python3 fantasy/opportunity.py            # build + report
"""

import json
import pathlib
import re
import unicodedata

import nflreadpy as nfl
import polars as pl

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "draftbot" / "opportunity.json"
VOR = HERE / "draftbot" / "vor.json"
SEASON = 2025
MIN_GAMES = 8


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def flag_for(pos, tpg, touches_pg, tds):
    """Volume thresholds mark true workhorses; TD cutoffs mark the tails of
    luck. Both must hold, or no flag: a mid-volume mid-TD player is priced
    about right and flagging him is noise."""
    if pos in ("WR", "TE"):
        if tpg >= 7.0 and tds <= 4:
            return "BUY"
        if tds >= 9 and tpg < 6.5:
            return "SELL"
    elif pos == "RB":
        if touches_pg >= 15.0 and tds <= 5:
            return "BUY"
        if tds >= 10 and touches_pg < 14.0:
            return "SELL"
    return None


def build():
    df = nfl.load_player_stats(seasons=[SEASON])
    df = df.filter(
        (pl.col("season_type") == "REG")
        & pl.col("position").is_in(["QB", "RB", "WR", "TE"])
    )
    agg = df.group_by("player_display_name", "position").agg(
        pl.len().alias("games"),
        pl.col("targets").sum().alias("targets"),
        pl.col("receptions").sum().alias("rec"),
        pl.col("carries").sum().alias("carries"),
        pl.col("target_share").mean().alias("tgt_share"),
        pl.col("wopr").mean().alias("wopr"),
        (pl.col("receiving_tds").sum() + pl.col("rushing_tds").sum()).alias("tds"),
        pl.col("receiving_yards").sum().alias("rec_yds"),
        pl.col("rushing_yards").sum().alias("rush_yds"),
    )

    snaps = nfl.load_snap_counts(seasons=[SEASON])
    snaps = snaps.filter(pl.col("game_type") == "REG").group_by("player").agg(
        pl.col("offense_pct").mean().alias("snap_pct")
    )
    snap_by_norm = {norm(r["player"]): r["snap_pct"] for r in snaps.to_dicts()}

    out = {}
    for r in agg.to_dicts():
        g = r["games"]
        if g < MIN_GAMES:
            continue
        pos = r["position"]
        tpg = r["targets"] / g
        touches = (r["targets"] + r["carries"]) / g
        rec = {
            "name": r["player_display_name"],
            "pos": pos,
            "games": g,
            "tpg": round(tpg, 1),
            "touches_pg": round(touches, 1),
            "tgt_share": round((r["tgt_share"] or 0.0), 3),
            "wopr": round((r["wopr"] or 0.0), 2),
            "tds": r["tds"],
            "snap_pct": round(snap_by_norm.get(norm(r["player_display_name"]), 0.0), 2),
        }
        rec["flag"] = flag_for(pos, tpg, touches, r["tds"])
        out[norm(r["player_display_name"])] = rec

    OUT.write_text(json.dumps(out))
    return out


def report(data):
    board = {}
    if VOR.exists():
        board = {
            k: v for k, v in json.loads(VOR.read_text())["players"].items()
        }
    print(f"{SEASON} volume overlay: {len(data)} players with {MIN_GAMES}+ games")
    for want in ("BUY", "SELL"):
        rows = [r for r in data.values() if r["flag"] == want]
        rows.sort(key=lambda r: -(r["tpg"] if r["pos"] != "RB" else r["touches_pg"]))
        print(f"\n{want} flags ({len(rows)}):")
        for r in rows:
            k = norm(r["name"])
            b = board.get(k)
            slot = f"board {b['pos']}{b['posRank']} adp {b['adp']:.0f}" if b else "off board"
            print(
                f"  {r['name']:<24} {r['pos']:<3} tgt/g {r['tpg']:>4}  "
                f"touch/g {r['touches_pg']:>5}  TDs {r['tds']:>2}  "
                f"snap {r['snap_pct']:.0%}  [{slot}]"
            )


if __name__ == "__main__":
    report(build())
