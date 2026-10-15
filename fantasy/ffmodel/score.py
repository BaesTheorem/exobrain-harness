"""score: proper scoring rules for the weekly forecasts.

Coverage at 50% and 90% says whether the bands are as wide as they claim,
but a forecaster can hit both with bands that are badly placed: wide where
the player is safe and narrow where he is not, or every median a little
high. A proper scoring rule cannot be gamed that way; its expected value is
best only when the forecast is the forecaster's true belief.

    interval_score(x, lo, hi, alpha)  Gneiting and Raftery (2007), eq. 43:
                                      width plus 2/alpha times the miss
    wis(x, median, bands)             the weighted interval score of the
                                      COVID-19 Forecast Hub (Bracher et al.
                                      2021), which approximates CRPS from a
                                      median and central intervals; lower is
                                      better, in points
    pit_bin(x, p90, p50, median)      which of six slices of the forecast
                                      distribution the outcome landed in;
                                      a calibrated forecaster fills them
                                      5/20/25/25/20/5 percent
    log_score(p, happened)            -ln of the probability given to what
                                      happened (win probabilities)
    season(recs)                      all of the above over filed weeks, for
                                      MIST and the baseline, from the JSON

INVARIANTS
- Pure functions over numbers and the filed forecast JSON; no network.
- WIS is only compared between forecasters scored on the same rows.
"""

from __future__ import annotations

import math

PIT_EXPECTED = (0.05, 0.20, 0.25, 0.25, 0.20, 0.05)
PIT_LABELS = ("<q05", "q05-25", "q25-50", "q50-75", "q75-95", ">q95")


def interval_score(x: float, lo: float, hi: float, alpha: float) -> float:
    s = hi - lo
    if x < lo:
        s += 2.0 / alpha * (lo - x)
    elif x > hi:
        s += 2.0 / alpha * (x - hi)
    return s


def wis(x: float, median: float, bands: list[tuple[float, float, float]]) -> float:
    """bands: (alpha, lo, hi) per central interval, e.g. (0.5, q25, q75), (0.1, q05, q95)."""
    k = len(bands)
    total = 0.5 * abs(x - median)
    for alpha, lo, hi in bands:
        total += alpha / 2.0 * interval_score(x, lo, hi, alpha)
    return total / (k + 0.5)


def pit_bin(x: float, p90: list, p50: list, median: float) -> int:
    edges = (p90[0], p50[0], median, p50[1], p90[1])
    for i, e in enumerate(edges):
        if x < e:
            return i
    return 5


def log_score(p: float, happened: bool) -> float:
    q = min(max(p if happened else 1.0 - p, 1e-6), 1.0)
    return -math.log(q)


def _mist_item(fp: dict, actual: float) -> dict | None:
    med = fp.get("median")
    if med is None or not fp.get("p50") or not fp.get("p90"):
        return None
    return {"wis": wis(actual, med, [(0.5, *fp["p50"]), (0.1, *fp["p90"])]),
            "pit": pit_bin(actual, fp["p90"], fp["p50"], med), "abs": abs(actual - med)}


def _base_item(bq: dict, actual: float) -> dict | None:
    if not bq or bq.get("q50") is None:
        return None
    p50, p90 = [bq["q25"], bq["q75"]], [bq["q05"], bq["q95"]]
    return {"wis": wis(actual, bq["q50"], [(0.5, *p50), (0.1, *p90)]),
            "pit": pit_bin(actual, p90, p50, bq["q50"]), "abs": abs(actual - bq["q50"])}


def season(recs: list[dict]) -> dict:
    """Proper scores over every settled player line, both forecasters on the
    same rows; plus the win-probability log score per forecaster."""
    rows = []
    wins = {"mist": [], "baseline": []}
    for r in recs:
        s = r.get("settled")
        if not s:
            continue
        fps = {p["name"]: p for p in r["forecast"]["players"]}
        for p in s["players"]:
            if "mist" not in p:
                continue
            a = p["mist"]["actual"]
            m = _mist_item(fps.get(p["name"]) or {}, a)
            b = _base_item((r.get("baseline") or {}).get("players", {}).get(p["name"]) or {}, a)
            if m and b:
                rows.append({"week": r["week"], "name": p["name"], "pos": p["pos"], "mist": m, "baseline": b})
        res = s["result"]
        wins["mist"].append(log_score(float(res["mist_win_prob"]), bool(res["won"])))
        if res.get("baseline_win_prob") is not None:
            wins["baseline"].append(log_score(float(res["baseline_win_prob"]), bool(res["won"])))
    out: dict = {"n": len(rows)}
    for who in ("mist", "baseline"):
        if not rows:
            break
        hist = [0] * 6
        for x in rows:
            hist[x[who]["pit"]] += 1
        out[who] = {"wis": round(sum(x[who]["wis"] for x in rows) / len(rows), 3),
                    "mae": round(sum(x[who]["abs"] for x in rows) / len(rows), 3),
                    "pit": [round(h / len(rows), 3) for h in hist],
                    "win_log_score": round(sum(wins[who]) / len(wins[who]), 3) if wins[who] else None,
                    "weeks": len(wins[who])}
    if rows:
        diffs = [x["mist"]["wis"] - x["baseline"]["wis"] for x in rows]
        mean = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / max(1, len(diffs) - 1))
        out["wis_diff"] = {"mist_minus_baseline": round(mean, 3), "se": round(sd / math.sqrt(len(diffs)), 3)}
    out["pit_expected"] = list(PIT_EXPECTED)
    out["pit_labels"] = list(PIT_LABELS)
    return out
