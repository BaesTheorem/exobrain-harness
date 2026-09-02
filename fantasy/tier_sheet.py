"""Build a draft-day tier sheet from the extracted Ringer board.

Tiers come from optimal 1-D k-means (exact DP, not Lloyd's) over **auction
value**, not over rank. That matters: auction dollars are already denominated in
value over a replacement-level player, so a tier break is a real drop in what a
pick is worth, and dollars are comparable across positions. Ranks are not.

Flags carried onto the sheet:
  W8       player's NFL bye is Week 8, which is Alex's idle week, so the bye is
           free. A within-tier tiebreak only -- never a reason to reach.
  SPLIT n  the three Ringer analysts disagree by n or more places. Contested
           players slide further than consensus players, so they are the ones to
           wait a beat on.

Deliberately omits the analysts' written blurbs. They are The Ringer's editorial
copy, they are useless at 26 seconds a pick, and this file should stay free of
anything that cannot be regenerated or shared.

Usage:
    python3 fantasy/tier_sheet.py [--board fantasy/ringer_board.json]
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Alex's league: 13 teams, 9 starters (QB/RB/RB/WR/WR/TE/FLEX/DST/K), 16 rounds.
TEAMS = 13
ROUNDS = 16
FANTASY_BYE = 8  # Chaos Legion sits idle in week 8, so a week-8 NFL bye is free
SPLIT_AT = 15  # expert rank spread that counts as genuinely contested

# How deep each position is worth tiering, and roughly how many tiers to cut it
# into. Past these depths the market prices everyone the same and so do we.
SHAPE = {
    "RB": (50, 8),
    "WR": (55, 8),
    "TE": (20, 6),
    "QB": (20, 5),
    "DEF": (11, 3),
    "K": (10, 3),
}


def kmeans_1d(xs: list[float], k: int) -> list[int]:
    """Exact 1-D k-means by dynamic programming. Returns a cluster id per point.

    xs must be sorted descending. Optimal clustering of sorted 1-D data is always
    contiguous, so the DP over split points is exact -- no seeding, no restarts,
    no run-to-run variation. n is small (<=55) so O(k*n^2) is free.
    """
    n = len(xs)
    k = max(1, min(k, n))
    pre = [0.0] * (n + 1)
    pre2 = [0.0] * (n + 1)
    for i, x in enumerate(xs):
        pre[i + 1] = pre[i] + x
        pre2[i + 1] = pre2[i] + x * x

    def sse(i: int, j: int) -> float:
        """Sum of squared deviations for xs[i..j] inclusive."""
        m = j - i + 1
        s = pre[j + 1] - pre[i]
        return max(0.0, (pre2[j + 1] - pre2[i]) - s * s / m)

    inf = float("inf")
    cost = [[inf] * n for _ in range(k)]
    back = [[0] * n for _ in range(k)]
    for j in range(n):
        cost[0][j] = sse(0, j)
    for c in range(1, k):
        for j in range(c, n):
            best, arg = inf, c
            for i in range(c, j + 1):
                v = cost[c - 1][i - 1] + sse(i, j)
                if v < best:
                    best, arg = v, i
            cost[c][j] = best
            back[c][j] = arg
    labels = [0] * n
    j = n - 1
    for c in range(k - 1, -1, -1):
        i = back[c][j] if c > 0 else 0
        for t in range(i, j + 1):
            labels[t] = c
        j = i - 1
    return labels


def value(p: dict) -> int | None:
    try:
        return int(p["auction"])
    except (TypeError, ValueError):
        return None


def build_tiers(players: list[dict]) -> dict[str, list[list[dict]]]:
    out: dict[str, list[list[dict]]] = {}
    for pos, (depth, ntiers) in SHAPE.items():
        pool = [p for p in players if p["pos"] == pos and value(p) is not None]
        pool.sort(key=lambda p: (-(value(p) or 0), p["rank"]))
        pool = pool[:depth]
        if not pool:
            continue
        labels = kmeans_1d([float(value(p) or 0) for p in pool], ntiers)
        tiers: list[list[dict]] = []
        for p, lab in zip(pool, labels, strict=True):
            while len(tiers) <= lab:
                tiers.append([])
            tiers[lab].append(p)
        out[pos] = [t for t in tiers if t]
    return out


def _norm_name(s: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "")
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s.lower())
    return re.sub(r"[^a-z]", "", s)


def _load_opportunity() -> dict:
    """TD-regression flags from the 2025 volume overlay, if it has been built
    (fantasy/opportunity.py). BUY = heavy volume with TD-shorted results,
    SELL = TD-inflated on modest volume. Volume repeats; touchdowns do not
    (last-year TDs -> next-year TDs R² = 0.079)."""
    path = HERE / "draftbot" / "opportunity.json"
    if not path.exists():
        return {}
    out = {}
    for rec in json.loads(path.read_text()).values():
        if rec.get("flag"):
            out[_norm_name(rec["name"])] = rec["flag"]
    return out


_OPPORTUNITY = _load_opportunity()


_FLAG_CLASS = {"W8": "w8", "BUY": "buy", "SELL": "sell"}


def flags(p: dict) -> list[str]:
    f = []
    if p.get("bye") == FANTASY_BYE:
        f.append("W8")
    if (p.get("expert_spread") or 0) >= SPLIT_AT:
        f.append(f"SPLIT {p['expert_spread']}")
    td = _OPPORTUNITY.get(_norm_name(p.get("name", "")))
    if td:
        f.append(td)
    return f


CSS = """
:root{--bg:#faf9f7;--sf:#fff;--sf2:#f2efea;--sf3:#e8e4dd;--out:#c9c3b8;
--ink:#1c1b18;--dim:#5c574e;--hi:#8c1d18;--ok:#1d4d2b}
*{box-sizing:border-box}
body{margin:0;padding:14px;background:var(--bg);color:var(--ink);
font:12px/1.35 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif}
h1{font-size:17px;margin:0 0 2px;letter-spacing:-.2px}
h2{font-size:11px;margin:0;padding:5px 7px;background:var(--ink);color:var(--bg);
text-transform:uppercase;letter-spacing:.9px;font-weight:600}
.sub{color:var(--dim);font-size:11px;margin:0 0 10px}
.rules{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid var(--out);
margin:0 0 12px;background:var(--sf)}
.rules div{padding:6px 9px;border-right:1px solid var(--out);border-bottom:1px solid var(--out)}
.rules b{color:var(--hi)}
.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;align-items:start}
.col{border:1px solid var(--out);background:var(--sf)}
.tier{border-top:1px solid var(--out)}
.tier:first-of-type{border-top:0}
.thead{display:flex;justify-content:space-between;padding:3px 7px;background:var(--sf3);
font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--dim)}
table{width:100%;border-collapse:collapse}
td{padding:2px 7px;vertical-align:baseline}
tr:nth-child(even){background:var(--sf2)}
.nm{font-weight:600}
.tm{color:var(--dim);font-size:10px}
.av{text-align:right;font-variant-numeric:tabular-nums;color:var(--dim);white-space:nowrap}
.fl{font-size:9px;letter-spacing:.4px}
.w8{color:var(--ok);font-weight:700}
.sp{color:var(--hi)}
.buy{color:var(--ok);font-weight:700;border:1px solid var(--ok);padding:0 2px}
.sell{color:var(--hi);font-weight:700;border:1px solid var(--hi);padding:0 2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.vor{margin-top:10px;border:1px solid var(--out);background:var(--sf)}
.vor table{font-size:11px}
.vor td{padding:1px 7px}
.slots{display:flex;flex-wrap:wrap;gap:0;border:1px solid var(--out);background:var(--sf)}
.slots span{padding:5px 11px;border-right:1px solid var(--out);font-weight:600}
.slots i{font-style:normal;color:var(--dim);font-weight:400}
@media print{body{padding:0;background:#fff;font-size:10px}
.cols{grid-template-columns:repeat(4,1fr)}h2{background:#000}}
"""


def render_html(tiers, players, meta) -> str:
    def rows(tier):
        out = []
        for p in tier:
            fl = flags(p)
            fs = " ".join(
                f'<span class="{_FLAG_CLASS.get(f, "sp")}">{html.escape(f)}</span>'
                for f in fl
            )
            out.append(
                f'<tr><td class="nm">{html.escape(p["name"])} '
                f'<span class="tm">{html.escape(str(p["team"]))}'
                f'{" &middot; bye " + str(p["bye"]) if p.get("bye") else ""}</span> '
                f'<span class="fl">{fs}</span></td>'
                f'<td class="av">${value(p)}</td></tr>'
            )
        return "".join(out)

    def column(pos):
        ts = tiers.get(pos, [])
        blocks = []
        for i, t in enumerate(ts, 1):
            lo, hi = value(t[-1]), value(t[0])
            rng = f"${lo}" if lo == hi else f"${lo}-${hi}"
            blocks.append(
                f'<div class="tier"><div class="thead"><span>Tier {i}</span>'
                f"<span>{rng}</span></div><table>{rows(t)}</table></div>"
            )
        return f'<div class="col"><h2>{pos}</h2>{"".join(blocks)}</div>'

    vor = sorted(
        [p for p in players if value(p) is not None and (value(p) or 0) >= 8],
        key=lambda p: (-(value(p) or 0), p["rank"]),
    )[:64]
    vr = "".join(
        f'<tr><td class="av">{i}</td><td class="nm">{html.escape(p["name"])}</td>'
        f'<td class="tm">{p["pos"]}</td><td class="av">${value(p)}</td></tr>'
        for i, p in enumerate(vor, 1)
    )
    half = len(vor) // 2 + len(vor) % 2
    vr_rows = vr.split("</tr>")
    left = "</tr>".join(vr_rows[:half]) + "</tr>"
    right = "</tr>".join(vr_rows[half:-1]) + "</tr>" if len(vr_rows) > half + 1 else ""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Draft sheet {meta["slug"]}</title><style>{CSS}</style></head><body>
<h1>Chaos Legion draft sheet &middot; full PPR &middot; {TEAMS} teams</h1>
<p class="sub">Tiers = optimal 1-D k-means over auction value (value over
replacement), from The Ringer's full-PPR board. {ROUNDS} rounds,
{TEAMS * ROUNDS} picks, ~{round(90 * 60 / (TEAMS * ROUNDS))}s per pick.
<span class="w8">W8</span> = NFL bye in week 8, which is your idle week, so it is
free (tiebreak only). <span class="sp">SPLIT</span> = the three analysts disagree
by {SPLIT_AT}+ places, so expect them to slide.
<span class="buy">BUY</span> = heavy 2025 volume, TD-shorted: the points come
back. <span class="sell">SELL</span> = TDs on modest volume: they will not
repeat (TD YoY R&sup2; = 0.08).</p>

<div class="rules">
<div><b>Take the tier, not the player.</b> Ask only: will anyone in this tier survive to my next turn?</div>
<div><b>Never chase a run.</b> When K/DST/QB start flying, take the skill player they skipped.</div>
<div><b>Wait on QB.</b> Elite QB is worth +$22 over replacement. Elite RB is +$52.</div>
<div><b>TE: top two or wait.</b> $37, $34, then a cliff to $21. The middle is a trap.</div>
<div><b>K and DST in the last two rounds.</b> Worst weekly projection accuracy of any position.</div>
<div><b>Stack RB/WR past your starters.</b> Surplus there cashes in. Surplus QB/TE/K/DST is dead weight.</div>
</div>

<div class="slots"><span>QB <i>__</i></span><span>RB <i>__ __</i></span>
<span>WR <i>__ __</i></span><span>TE <i>__</i></span><span>FLEX <i>__</i></span>
<span>DST <i>__</i></span><span>K <i>__</i></span>
<span>BENCH <i>__ __ __ __ __ __ __</i></span></div>

<div class="cols" style="margin-top:10px">
{column("RB")}{column("WR")}{column("TE")}{column("QB")}
</div>
<div class="two">{column("DEF")}{column("K")}</div>

<div class="vor"><h2>Best available by value over replacement (cross-position)</h2>
<div class="two" style="margin:0;gap:0">
<table>{left}</table><table>{right}</table></div></div>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=str(HERE / "ringer_board.json"))
    ap.add_argument("--out", default=str(HERE / "draft-sheet.html"))
    args = ap.parse_args()

    meta = json.loads(Path(args.board).read_text())
    players = meta["players"]
    tiers = build_tiers(players)
    Path(args.out).write_text(render_html(tiers, players, meta))

    for pos in ("RB", "WR", "TE", "QB", "DEF", "K"):
        ts = tiers.get(pos, [])
        sizes = "/".join(str(len(t)) for t in ts)
        print(f"{pos:<4} {len(ts)} tiers ({sizes})")
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
