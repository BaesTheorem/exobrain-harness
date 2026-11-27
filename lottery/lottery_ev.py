#!/usr/bin/env python3
"""Expected-value math and public-data readers for the lottery games near Kansas City.

What it reads: the Missouri Lottery game pages and Scratchers prize tables
(molottery.com) and the Kansas Lottery results API (playonkansas.com).
What it computes: the return per dollar of each rolling-jackpot game at the
current jackpot, before and after tax, and the return per dollar on the unsold
tickets of every Missouri Scratchers game.

INVARIANTS (do not break when editing):
- Read-only, public pages only. No login, no account, no purchase.
- At most one request per second per host, generic User-Agent. molottery.com
  truncates a page when the Accept-Language header is missing, so it stays.
- Break-even numbers are computed from the prize tables in GAMES. Do not
  replace them with typed constants. When a lottery changes a prize table,
  change GAMES, and the tests show what moved.
- The tax model is a 2026 single-filer estimate (IRS brackets, the 90 percent
  loss rule of IRC 165(d), Missouri 4.7 percent, Kansas 5.58 percent with no
  loss deduction). It is a planning number, not tax advice.
- The Scratchers estimator takes the sold fraction from the mid prize tiers.
  The lowest tiers are under-claimed, so their counts overstate what is left.
"""

from __future__ import annotations

import html
import json
import math
import re
import time
import urllib.request
from dataclasses import dataclass

UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json",
}
MO = "https://www.molottery.com"
KS_API = "https://gateway-web.loyalty.playonkansas.com/services"

# ---- tax model, tax year 2026, single filer ---------------------------------
FED_BRACKETS = (
    (12400, 0.10),
    (50400, 0.12),
    (105700, 0.22),
    (201775, 0.24),
    (256225, 0.32),
    (640600, 0.35),
    (float("inf"), 0.37),
)
STANDARD_DEDUCTION = 16100
MO_RATE = 0.047
KS_RATE = 0.0558
LOSS_DEDUCTION_SHARE = 0.90
OTHER_INCOME = 30000  # assumed ordinary income of the player


def fed_tax(taxable: float) -> float:
    tax, low = 0.0, 0.0
    for high, rate in FED_BRACKETS:
        if taxable > low:
            tax += (min(taxable, high) - low) * rate
        low = high
    return tax


def salt_cap(agi: float) -> float:
    return max(10000.0, 40400.0 - 0.3 * max(0.0, agi - 505000.0))


def extra_tax(prizes: float, wagers: float, wagers_lost: float, state: str = "MO") -> float:
    """Tax added by a year of play: prizes won, money wagered, money on losing wagers."""
    gains = max(prizes - (wagers - wagers_lost), 0.0)
    deduction = min(LOSS_DEDUCTION_SHARE * wagers_lost, gains)
    agi = OTHER_INCOME + gains
    mo_tax = MO_RATE * max(0.0, agi - max(deduction, STANDARD_DEDUCTION))
    # Kansas taxes its lottery prizes at source with no deduction for losing
    # tickets. Missouri credits that tax up to its own, so the larger one binds.
    state_tax = max(KS_RATE * gains, mo_tax) if state == "KS" else mo_tax
    itemized = deduction + min(state_tax, salt_cap(agi))
    federal = fed_tax(max(0.0, agi - max(itemized, STANDARD_DEDUCTION)))
    base = OTHER_INCOME - STANDARD_DEDUCTION
    baseline = fed_tax(max(0.0, base)) + MO_RATE * max(0.0, base)
    return federal + state_tax - baseline


# ---- rolling-jackpot games --------------------------------------------------
@dataclass(frozen=True)
class Game:
    key: str
    name: str
    state: str
    price: float
    jackpot_odds: float  # 1 in N for one purchase of `price` dollars
    tiers: tuple[tuple[float, float], ...]  # fixed prizes as (prize, 1 in N)
    cash_ratio: float  # cash value as a share of the advertised jackpot
    base_sales: float  # purchases per draw at a small jackpot
    sales_slope: float  # extra purchases per advertised jackpot dollar
    unpopular: float  # co-winner rate for the least-picked numbers, 1.0 if unmeasured

    @property
    def low_return(self) -> float:
        return sum(prize / odds for prize, odds in self.tiers)

    @property
    def naive_break_even(self) -> float:
        """Advertised jackpot at which a ticket returns its price, no tax, no split."""
        return (self.price - self.low_return) * self.jackpot_odds / self.cash_ratio


GAMES = {
    # Show Me Cash: 5 of 39, daily. Sales response and the 0.53 factor are
    # measured from the Lottery's own draw file (6,654 draws, 2008 to 2026).
    "smc": Game(
        "smc", "Show Me Cash (MO)", "MO", 1.0, 575757,
        # exact counts of winning combinations: 170, 5,610 and 59,840 of 575,757
        ((250, 575757 / 170), (10, 575757 / 5610), (1, 575757 / 59840)),
        1.0, 45000, 0.30, 0.53,
    ),
    # MO Millions: 6 of 42 with Bulls-Eye, $2, advertised jackpot is an annuity.
    "mom": Game(
        "mom", "MO Millions (MO)", "MO", 2.0, 5245786,
        ((1500, 29143.26), (750, 145716.28), (50, 832.66), (25, 1665.33), (6, 73.47), (3, 73.47), (2, 17.81)),
        0.5, 81000, 0.01, 1.0,
    ),
    # Super Kansas Cash: $1 buys 2 boards of 5 of 32 plus a Cash Ball of 25.
    "skc": Game(
        "skc", "Super Kansas Cash (KS)", "KS", 1.0, 2517200,
        # exact counts per board of 5,034,400: 24, 135, 3,240, 3,510, 84,240, 29,250, 87,750
        tuple((prize, 2517200 / count) for prize, count in (
            (2000, 24), (250, 135), (25, 3240), (25, 3510), (2, 84240), (2, 29250), (1, 87750),
        )),
        1.0, 45000, 0.03, 1.0,
    ),
}


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def ticket_return(game: Game, advertised: float, taxed: bool = False, unpopular: bool = False) -> float:
    """Expected return of one purchase, per dollar spent."""
    cash = advertised * game.cash_ratio
    lam = (game.base_sales + game.sales_slope * advertised) / game.jackpot_odds
    if unpopular:
        lam *= game.unpopular
    value = game.low_return
    for others in range(0, int(lam + 10 * math.sqrt(lam) + 15)):
        share = cash / (1 + others)
        if taxed:
            share -= extra_tax(share, game.price, 0.0, game.state)
        value += poisson(others, lam) * share / game.jackpot_odds
    return value / game.price


def break_even(game: Game, taxed: bool = False, unpopular: bool = False) -> float:
    """Advertised jackpot at which one purchase returns exactly its price."""
    # The return rises with the jackpot over the range that occurs in practice.
    # Far above it, sales (and so jackpot sharing) grow without limit in this
    # model, so the search stays inside 40 times the no-tax, no-split level.
    low, high = 0.0, 40 * game.naive_break_even
    if ticket_return(game, high, taxed, unpopular) < 1.0:
        return float("inf")
    for _ in range(80):
        mid = (low + high) / 2
        if ticket_return(game, mid, taxed, unpopular) < 1.0:
            low = mid
        else:
            high = mid
    return high


def coverage(game: Game, advertised: float, others: int) -> dict:
    """Result of buying every combination once, with `others` co-winners."""
    cost = game.jackpot_odds * game.price
    lower = game.low_return * game.jackpot_odds
    winners = game.jackpot_odds * sum(1 / odds for _, odds in game.tiers)
    prizes = advertised * game.cash_ratio / (1 + others) + lower
    pre = prizes - cost
    tax = extra_tax(prizes, cost, cost - winners * game.price, game.state)
    lam = (game.base_sales + game.sales_slope * advertised) / game.jackpot_odds
    return {"cost": cost, "pre_tax": pre, "tax": tax, "after_tax": pre - tax, "chance": poisson(others, lam)}


# ---- readers ----------------------------------------------------------------
def http_get(url: str, tries: int = 3) -> str:
    text = ""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace")
        if "molottery.com" not in url or "</html>" in text:
            return text
        time.sleep(2 + attempt)
    return text


def parse_money(text: str) -> float | None:
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(Million|Billion)?", text)
    if not m:
        return None
    scale = {"Million": 1e6, "Billion": 1e9}.get(m.group(2) or "", 1.0)
    return float(m.group(1).replace(",", "")) * scale


def mo_jackpot(path: str) -> dict:
    """Next advertised jackpot and draw day from a Missouri game page."""
    page = http_get(f"{MO}/{path}")
    m = re.search(r"Next Estimated Jackpot:(.{0,200}?)<br>\s*Next Drawing:\s*([^<\n]+)", page, re.S)
    if not m:
        return {"jackpot": None, "next_draw": None}
    return {"jackpot": parse_money(m.group(1)), "next_draw": m.group(2).strip()}


def ks_last_draw(game_id: int = 8) -> dict:
    """Latest completed Kansas draw: the jackpot it carried and whether it was hit."""
    data = json.loads(http_get(f"{KS_API}/jackpot/api/v1/jackpot-results/games/{game_id}"))
    tiers = data.get("prizeTiers", [])
    top = next((t for t in tiers if t.get("name") == "m5-cb"), {})
    # The API often shows a new draw with every winner count at zero for some
    # days. Then "no jackpot winner" is unknown, and the caller must say so.
    published = any(t.get("shareCount") for t in tiers)
    return {
        "jackpot": data.get("cashAmount"),
        "draw": (data.get("drawDate") or "")[:10],
        "winners": (top.get("shareCount") or 0) if published else None,
    }


# ---- Missouri Scratchers ----------------------------------------------------
def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_scratcher(page: str, game_id: int) -> dict:
    game: dict = {"game": game_id}
    m = re.search(r'<div class="scratchers-single">\s*<h1>(.*?)</h1>', page, re.S)
    game["name"] = _clean(m.group(1)) if m else ""
    info = {}
    for title, body in re.findall(
        r'scratchers-single-info__title">(.*?)</div>\s*<div class="scratchers-single-info__body">(.*?)</div>',
        page,
        re.S,
    ):
        info[_clean(title).rstrip(":*").strip()] = _clean(body)
    game["start"] = info.get("Official Start Date", "")
    game["end"] = info.get("End Date", "")
    game["price"] = parse_money(info.get("Ticket Price", ""))
    m = re.search(r"1 in ([\d.]+)", info.get("Average Chances", ""))
    game["odds"] = float(m.group(1)) if m else None
    tiers = []
    table = re.search(r"<th>Prize Level</th>.*?</table>", page, re.S)
    if table:
        for row in re.findall(r"<tr>(.*?)</tr>", table.group(0), re.S):
            cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) == 3:
                tiers.append(
                    {
                        "value": parse_money(cells[0]),
                        "total": int(cells[1].replace(",", "") or 0),
                        "unclaimed": int(cells[2].replace(",", "") or 0),
                    }
                )
    game["tiers"] = tiers
    return game


def fetch_scratchers(progress=None) -> list[dict]:
    listing = http_get(f"{MO}/scratchers-list.do")
    ids = sorted({int(g) for g in re.findall(r"scratchers\.do\?method=d&(?:amp;)?game=(\d+)", listing)})
    games = []
    for n, gid in enumerate(ids, 1):
        time.sleep(1.0)
        games.append(parse_scratcher(http_get(f"{MO}/scratchers.do?method=d&game={gid}"), gid))
        if progress:
            progress(n, len(ids))
    return games


def net_prize(value: float) -> float:
    """Prize after a flat tax estimate: 41 percent from $100,000, 27 percent from $600."""
    return value * (0.59 if value >= 100000 else 0.73 if value >= 600 else 1.0)


def scratcher_return(game: dict) -> dict | None:
    """Return per dollar on the unsold tickets of one Scratchers game."""
    tiers = [t for t in game["tiers"] if t["value"]]
    price, odds = game.get("price"), game.get("odds")
    if not tiers or not price or not odds:
        return None
    printed = sum(t["total"] for t in tiers) * odds
    mid = (
        [t for t in tiers if 2.5 * price <= t["value"] < 600 and t["total"] >= 1000]
        or [t for t in tiers if t["value"] < 600 and t["total"] >= 1000][1:]
        or [t for t in tiers if t["total"] >= 1000]
    )
    if not mid:
        return None
    sold = sum(t["total"] - t["unclaimed"] for t in mid) / sum(t["total"] for t in mid)
    face = printed * price
    common = [t for t in tiers if t["total"] >= 200]
    rare = [t for t in tiers if t["total"] < 200]
    common_share = sum(t["value"] * t["total"] for t in common) / face
    common_net = sum(net_prize(t["value"]) * t["total"] for t in common) / face
    rare_left = sum(t["value"] * t["unclaimed"] for t in rare)
    rare_net = sum(net_prize(t["value"]) * t["unclaimed"] for t in rare)
    left = max(1.0 - sold, 1e-9)
    top = max(tiers, key=lambda t: t["value"])
    return {
        "game": game["game"],
        "name": game["name"],
        "price": price,
        "on_sale": game.get("end") == "TBD",
        "printed_return": sum(t["value"] * t["total"] for t in tiers) / face,
        "sold": sold,
        "return_now": common_share + rare_left / (face * left),
        "return_after_tax": common_net + rare_net / (face * left),
        "turns_positive_at": 1.0 - rare_left / ((1.0 - common_share) * face),
        "face_value_left": face * left,
        "top_prizes_left": top["unclaimed"],
        "top_prizes_total": top["total"],
        "top_prize": top["value"],
    }
