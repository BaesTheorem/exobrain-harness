"""fantasy/bin/stash-scan: injured free agents priced as playoff stashes.

Its failure mode is the quiet one (no candidate looks like "nobody worth
stashing"), so a planted star must PASS, and the cases that must never pass
are pinned: a player who would not start for us, season-ending news, and an
IR route when the slot is taken or the player is only OUT.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "fantasy"))
_loader = importlib.machinery.SourceFileLoader("stash_scan", str(REPO / "fantasy" / "bin" / "stash-scan"))
spec = importlib.util.spec_from_loader("stash_scan", _loader)   # no .py suffix, so name the loader
assert spec is not None and spec.loader is not None
stash_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stash_scan)

BENCH, IR = stash_scan.BENCH, stash_scan.IR


def r(pid, name, pos, slot_id, rate, status="", avail="FA"):
    """A row whose ros_rate is `rate`: a healthy player projects it this week,
    an injured one (projection 0) carries it as his rest-of-season prior."""
    proj = 0.0 if status in ("OUT", "IR") else rate
    return {"id": pid, "name": name, "pos": pos, "slotId": slot_id, "status": status, "avail": avail,
            "team": "KC", "proj": proj, "season_proj": rate * 17, "season_actual": None, "owned": 5.0}


def roster(ir_holder=False):
    rows = [r(1, "QB1", "QB", 0, 20.0), r(2, "RB1", "RB", 2, 15.0), r(3, "RB2", "RB", 2, 12.0),
            r(4, "WR1", "WR", 4, 16.0), r(5, "WR2", "WR", 4, 11.0), r(6, "TE1", "TE", 6, 10.0),
            r(7, "Flex", "WR", 23, 10.0), r(8, "Bench RB", "RB", BENCH, 8.0), r(9, "Bench WR", "WR", BENCH, 7.0)]
    if ir_holder:
        rows.append(r(10, "Our IR", "WR", IR, 9.0, status="IR"))
    return rows


def run(pool, ir_holder=False, news=None):
    return stash_scan.scan(10, roster(ir_holder), pool, stash_scan.DEFAULT_WEIGHTS, news=news)


def test_a_star_on_ir_passes_for_the_open_ir_slot():
    out = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")])
    assert out["ir_open"] and out["floors"]["WR"] == 10.0
    c = out["candidates"][0]
    assert c["back_rate"] == pytest.approx(18.0 * stash_scan.FACTOR_IR)
    assert c["units"] == pytest.approx(2.0 + 11.0 + 12.0), "no return date: weeks 15-17 only"
    assert c["passes"] and c["route"] == "IR", "the planted PASS must show"


def test_a_stash_who_would_not_start_for_us_is_worth_nothing():
    out = run([r(21, "Fine WR", "WR", BENCH, 11.0, status="IR")])   # 11 x 0.89 = 9.8, under our 10.0
    assert out["candidates"] == [] and out["below_floor"] == 1


def test_season_ending_news_is_never_a_candidate():
    news = {20: [{"headline": "Star WR out for season", "story": "He suffered a torn ACL, a season-ending injury."}]}
    out = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")], news=news)
    assert out["candidates"] == []


def test_out_is_not_ir_and_a_held_slot_is_not_open():
    out = run([r(22, "Out WR", "WR", BENCH, 18.0, status="OUT")])
    c = out["candidates"][0]
    assert c["factor"] == stash_scan.FACTOR_OTHER and c["route"] == "bench", "OUT does not go in the IR slot"
    held = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")], ir_holder=True)
    assert not held["ir_open"] and held["candidates"][0]["route"] == "bench"


def test_a_return_date_moves_the_start_week():
    news = {20: [{"headline": "Star WR progressing", "story": "A return following the team's Week 12 bye is the goal."}]}
    out = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")], news=news)
    c = out["candidates"][0]
    assert c["from_week"] == 13 and c["units"] == pytest.approx(1.0 + 1.0 + 2.0 + 11.0 + 12.0), "weeks 13-17"


def test_return_hint_reads_the_shapes_the_news_uses():
    hint = stash_scan.return_hint
    assert hint([{"story": "a return to game action following the Saints' Week 8 bye is likely"}], 6)[0] == 9
    assert hint([{"story": "He is expected to miss 4-6 weeks."}], 6)[0] == 12
    assert hint([{"story": "He was hurt in Week 3."}], 6) == (None, False, ""), "a past week is not a return date"
    assert hint([{"headline": "Out for the season"}], 6)[1] is True


def test_a_stale_leverage_cache_falls_back_to_the_defaults(tmp_path):
    cache = tmp_path / "leverage.json"
    cache.write_text('{"weight": {"15": 1.5, "16": 8.0, "17": 9.5}}')
    weights, source = stash_scan.weights_cached(cache)
    assert weights[16] == 8.0 and source == "season_sim --leverage"
    stale = cache.stat().st_mtime + stash_scan.LEVERAGE_MAX_AGE + 60
    assert stash_scan.weights_cached(cache, now=stale)[0] == stash_scan.DEFAULT_WEIGHTS


def test_the_banner_offers_a_player_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stash_scan, "STATE", tmp_path / "stash-scan.json")
    monkeypatch.setattr(stash_scan, "web_urls", lambda: {"team": "https://example.invalid/team"})
    monkeypatch.setattr(stash_scan.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    out = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")])
    assert stash_scan.banner(out) == "Star WR"
    cmd = calls[0]
    assert "--discord" in cmd and any(a.startswith("Do it=cmd:") for a in cmd)
    assert any('espn-tx ir \\"Star WR\\"' in a for a in cmd), "Do it names the IR move"
    assert stash_scan.banner(out) is None and len(calls) == 1, "never offered twice"
    held = run([r(20, "Star WR", "WR", BENCH, 18.0, status="IR")], ir_holder=True)
    monkeypatch.setattr(stash_scan, "STATE", tmp_path / "other.json")
    assert stash_scan.banner(held) is None, "no banner while the IR slot is held"
