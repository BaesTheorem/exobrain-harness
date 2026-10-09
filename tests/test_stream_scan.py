"""fantasy/bin/stream-scan: the D/ST rule must look at our own bench first.

On 2026-10-06 it offered a waiver D/ST over the starter while a better D/ST
sat on our bench, because it read only the D/ST slot.
"""

import importlib.machinery
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("stream_scan", str(REPO / "fantasy" / "bin" / "stream-scan"))
spec = importlib.util.spec_from_loader("stream_scan", _loader)   # no .py suffix, so name the loader
assert spec is not None and spec.loader is not None
stream_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stream_scan)

SLATE = [{"home": {"abbrev": "LAR"}, "away": {"abbrev": "BUF"}, "implied_home": 28.5, "implied_away": 26.0},
         {"home": {"abbrev": "DAL"}, "away": {"abbrev": "TB"}, "implied_home": 28.0, "implied_away": 19.5}]
POOL = [{"name": "Jets D/ST", "opp": "CLE", "implied_opp": 18.5, "proj": 7.7, "avail": "WVR"}]
STARTER = {"name": "Rams D/ST", "team": "LAR", "opp": "BUF", "proj": 4.6}
BENCH = {"name": "Cowboys D/ST", "team": "DAL", "opp": "TB", "proj": 7.5}


def test_free_agent_stream_fires_with_no_bench_dst():
    v = stream_scan.scan({"D/ST": STARTER}, SLATE, POOL, [])["dst"]
    assert v["stream"] and v["best_fa"][0]["name"] == "Jets D/ST"


def test_better_bench_dst_is_a_lineup_move_not_a_claim():
    v = stream_scan.scan({"D/ST": STARTER}, SLATE, POOL, [], [BENCH])["dst"]
    assert not v["stream"] and v["start_bench"]["name"] == "Cowboys D/ST"


def test_worse_bench_dst_changes_nothing():
    v = stream_scan.scan({"D/ST": BENCH}, SLATE, POOL, [], [STARTER])["dst"]
    assert "start_bench" not in v


LOCKED_STARTER = {"name": "Cowboys D/ST", "team": "DAL", "opp": "TB", "proj": 7.4,
                  "kick": "Thu 7:15p (locked)", "actual": -2.0}
BENCH_RAMS = {"name": "Rams D/ST", "team": "LAR", "opp": "BUF", "proj": 4.4, "kick": "Mon 7:15p"}
SLATE_AFTER_KICKOFF = [{"home": {"abbrev": "LAR"}, "away": {"abbrev": "BUF"}, "implied_home": 28.5,
                        "implied_away": 25.8}]   # DAL vs TB is gone: the game started


def test_locked_starter_is_never_swapped():
    """2026-10-08: the gate fired ten minutes after the Cowboys locked."""
    v = stream_scan.scan({"D/ST": LOCKED_STARTER}, SLATE_AFTER_KICKOFF, [], [], [BENCH_RAMS])["dst"]
    assert "start_bench" not in v


def test_missing_line_is_not_a_bye():
    """A starter whose line left the API is not a starter with no matchup."""
    unlocked = {"name": "Cowboys D/ST", "team": "DAL", "opp": "TB", "proj": 7.4, "kick": "Thu 7:15p"}
    v = stream_scan.scan({"D/ST": unlocked}, SLATE_AFTER_KICKOFF, [], [], [BENCH_RAMS])["dst"]
    assert "start_bench" not in v


def test_bye_starter_still_yields_to_the_bench():
    bye = {"name": "Cowboys D/ST", "team": "DAL", "opp": "BYE", "proj": 0.0, "kick": ""}
    v = stream_scan.scan({"D/ST": bye}, SLATE_AFTER_KICKOFF, [], [], [BENCH_RAMS])["dst"]
    assert v["start_bench"]["name"] == "Rams D/ST"
