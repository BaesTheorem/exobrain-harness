"""Tests for fantasy/ffmodel/role.py: the discounted filter, the
Beta-Binomial, and the whole model on a planted league whose roles are
known. Every fixture is planted; nothing here touches the network.

The repo's pytest environment has numpy but neither polars nor scipy. The
filter tests need numpy only and always run; the Beta-Binomial and
planted-league tests skip cleanly where polars or scipy is missing."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fantasy"))

from ffmodel import role  # noqa: E402  (role imports polars and scipy lazily)


@pytest.fixture
def pl():
    """polars, for the planted-league tests (scipy too: the fit uses it)."""
    pytest.importorskip("scipy")
    return pytest.importorskip("polars")

# ---- the filter -------------------------------------------------------------------


def test_panel_state_reads_only_earlier_rows():
    keys = np.array(["a", "a", "a", "b", "b"])
    seasons = np.array([2020, 2020, 2021, 2020, 2020])
    panel = role.Panel(keys, seasons)
    v = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    got = panel.state(v, 0.5, 0.5)
    # a: nothing; 0.5 * 1; season boundary: 0.5 * 0.5 * (0.5 + 2). b restarts.
    assert np.allclose(got, [0.0, 0.5, 0.625, 0.0, 4.0])
    # Changing a row never changes its own state or an earlier one.
    v2 = v.copy()
    v2[2] = 1e6
    v2[4] = -1e6
    assert np.array_equal(panel.state(v2, 0.5, 0.5), got)


def test_panel_delta_zero_resets_at_the_season():
    panel = role.Panel(np.array(["a", "a", "a"]), np.array([2020, 2020, 2021]))
    got = panel.state(np.array([3.0, 5.0, 7.0]), 1.0, 0.0)
    assert np.allclose(got, [0.0, 3.0, 0.0])


def test_bb_loglik_is_a_distribution_and_tends_to_the_binomial():
    from math import comb, log

    pytest.importorskip("scipy")

    n = np.arange(0, 11, dtype=float)
    big = np.full(n.size, 10.0)
    p = np.exp(role.bb_loglik(n, big, np.full(n.size, 2.0), np.full(n.size, 3.0)))
    assert abs(p.sum() - 1.0) < 1e-9
    a, b = 3e5, 7e5   # mean 0.3, almost no spread
    got = role.bb_loglik(np.array([3.0]), np.array([10.0]), np.array([a]), np.array([b]))[0]
    want = log(comb(10, 3)) + 3 * log(0.3) + 7 * log(0.7)
    assert abs(got - want) < 1e-3


# ---- a planted league -------------------------------------------------------------

TEAMS = ("AAA", "BBB", "CCC", "DDD")
# (pos, slot, share of targets, of carries, of pass attempts, snap share)
ROLES = (("QB", "qb", 0.0, 0.08, 1.0, 1.0), ("RB", "rb1", 0.10, 0.65, 0.0, 0.7),
         ("RB", "rb2", 0.05, 0.25, 0.0, 0.3), ("WR", "wr1", 0.28, 0.0, 0.0, 0.95),
         ("WR", "wr2", 0.20, 0.0, 0.0, 0.85), ("WR", "wr3", 0.10, 0.0, 0.0, 0.5),
         ("TE", "te1", 0.17, 0.0, 0.0, 0.8))


def _split(rng, total: int, shares: list[float]) -> np.ndarray:
    """A multinomial split of a team total; the remainder goes to players
    outside the frame."""
    p = np.asarray(shares + [max(0.0, 1.0 - sum(shares))])
    return rng.multinomial(int(total), p / p.sum())[:-1]


def planted(pl, seed: int = 7, seasons=(2019, 2020)) -> dict:
    rng = np.random.default_rng(seed)
    prow, trow, rost = [], [], []
    for s in seasons:
        for w in range(1, 18):
            for home, away in ((TEAMS[0], TEAMS[1]), (TEAMS[2], TEAMS[3])):
                total, spread = rng.uniform(38, 52), rng.uniform(-7, 7)
                for team, imp, spr in ((home, (total + spread) / 2, spread), (away, (total - spread) / 2, -spread)):
                    t = {"season": s, "week": w, "team": team, "implied": imp, "spread": spr, "played": True,
                         "T_tgt": float(rng.poisson(8 + imp)), "T_car": float(rng.poisson(max(5.0, 34 - 0.4 * imp + 0.4 * spr))),
                         "T_snaps": 65.0}
                    t["T_att"] = t["T_tgt"] + 2
                    t["T_db"] = t["T_db_part"] = t["T_att"] + 3
                    t["T_rz"] = float(rng.binomial(int(t["T_tgt"]), 0.2))
                    t["T_gl"] = float(rng.binomial(int(t["T_car"]), 0.1))
                    t["T_ptd"] = float(rng.poisson(0.06 * imp))
                    t["T_rtd"] = float(rng.poisson(0.03 * imp))
                    t["T_ptd_rz"] = float(rng.binomial(int(t["T_ptd"]), 0.7))
                    t["T_rtd_gl"] = float(rng.binomial(int(t["T_rtd"]), 0.7))
                    trow.append(t)
                    tg = _split(rng, int(t["T_tgt"]), [r[2] for r in ROLES])
                    ca = _split(rng, int(t["T_car"]), [r[3] for r in ROLES])
                    at = _split(rng, int(t["T_att"]), [r[4] for r in ROLES])
                    rz = _split(rng, int(t["T_rz"]), [r[2] for r in ROLES])
                    gl = _split(rng, int(t["T_gl"]), [r[3] for r in ROLES])
                    ptd = _split(rng, int(t["T_ptd"]), [r[2] for r in ROLES])
                    rtd = _split(rng, int(t["T_rtd"]), [r[3] for r in ROLES])
                    for i, (pos, slot, *_rest, snap) in enumerate(ROLES):
                        pid = f"{team}-{slot}"
                        rec_y, rush_y, pass_y = 1.5 * tg[i], 0.45 * ca[i], 0.25 * at[i]
                        pts = rec_y + rush_y + pass_y + 6 * (ptd[i] + rtd[i]) + (4 * t["T_ptd"] if pos == "QB" else 0)
                        prow.append({"season": s, "week": w, "player_id": pid, "name": pid, "pos": pos, "team": team,
                                     "targets": float(tg[i]), "carries": float(ca[i]), "attempts": float(at[i]),
                                     "rec_y": rec_y, "rush_y": rush_y, "pass_y": pass_y, "pts": float(pts),
                                     "rz_tgt": float(rz[i]), "gl_car": float(gl[i]),
                                     "snaps": float(rng.binomial(65, snap)),
                                     "routes": float(rng.binomial(int(t["T_db"]), snap)), "query": False})
                        rost.append({"season": s, "week": w, "team": team, "position": pos, "status": "ACT",
                                     "gsis_id": pid, "pfr_id": pid, "game_type": "REG", "pos": pos})
    return {"players": pl.DataFrame(prow), "teams": pl.DataFrame(trow), "roster": pl.DataFrame(rost)}


def _by_id(out: dict, season: int, week: int) -> dict[str, float]:
    sel = (out["season"] == season) & (out["week"] == week)
    return dict(zip(out["player_id"][sel], out["role"][sel], strict=True))


def test_planted_roles_are_recovered(pl):
    data = planted(pl)
    prm = role.fit(data, [2019], "base")
    out = role.project(data, prm)
    late = (out["season"] == 2020) & (out["week"] == 17)
    share = dict(zip(out["player_id"][late], out["tgt_share"][late], strict=True))
    for team in TEAMS:
        assert abs(share[f"{team}-wr1"] - 0.28) < 0.06, share[f"{team}-wr1"]
        assert share[f"{team}-wr1"] > share[f"{team}-wr2"] > share[f"{team}-wr3"]
    pts = _by_id(out, 2020, 17)
    for team in TEAMS:
        assert pts[f"{team}-wr1"] > pts[f"{team}-wr3"]
        assert pts[f"{team}-rb1"] > pts[f"{team}-rb2"]
    # Team targets were planted as 8 + implied.
    b = prm["volume"]["T_tgt"]["coef"]
    assert abs(b[1] - 1.0) < 0.25 and abs(b[0] - 8.0) < 6.0, b


def test_future_box_scores_never_move_a_projection(pl):
    data = planted(pl)
    prm = role.fit(data, [2019], "routes")
    out = role.project(data, prm)
    fut = (pl.col("season") == 2020) & (pl.col("week") >= 10)
    num = ["targets", "carries", "attempts", "rz_tgt", "gl_car", "snaps", "routes", "rec_y", "rush_y", "pass_y", "pts"]
    bad = {"players": data["players"].with_columns(
               *[pl.when(fut).then(pl.col(c) * 5 + 3).otherwise(pl.col(c)).alias(c) for c in num]),
           "teams": data["teams"].with_columns(
               *[pl.when(fut).then(pl.col(c) * 5 + 3).otherwise(pl.col(c)).alias(c) for c in role.TEAM_COUNTS]),
           "roster": data["roster"]}
    out2 = role.project(bad, prm)
    upto = (out["season"] == 2019) | (out["week"] <= 10)
    assert np.array_equal(out["role"][upto], out2["role"][upto])
    # Positive control: the corrupted weeks feed later projections.
    after = (out["season"] == 2020) & (out["week"] > 10)
    assert np.abs(out["role"][after] - out2["role"][after]).max() > 0.5
    # The fit reads only its training seasons.
    assert role.fit(bad, [2019], "routes")["calib"] == prm["calib"]


def test_week_projection_on_cut_data_equals_the_vectorized_projection(pl):
    data = planted(pl)
    prm = role.fit(data, [2019], "base")
    vec = _by_id(role.project(data, prm), 2020, 9)
    uni = data["players"].filter((pl.col("season") == 2020) & (pl.col("week") == 9)).select(
        [pl.col("player_id").alias("gsis_id"), "pos", "team"])
    cut = role.week_projection(2020, 9, "base", params=prm, data=data, universe=uni)
    assert set(cut) == set(vec)
    assert max(abs(cut[k] - round(v, 2)) for k, v in vec.items()) <= 0.01
    # The default universe (the weekly roster) gives the same players.
    assert set(role.week_projection(2020, 9, "base", params=prm, data=data)) == set(vec)


def test_truncate_keeps_the_weeks_line_and_drops_its_results(pl):
    data = planted(pl)
    cut = role.truncate(data, 2020, 5)
    assert cut["players"].filter((pl.col("season") == 2020) & (pl.col("week") >= 5)).is_empty()
    wk = cut["teams"].filter((pl.col("season") == 2020) & (pl.col("week") == 5))
    assert wk.height == len(TEAMS)
    assert wk["implied"].is_not_null().all() and wk["T_tgt"].is_null().all() and not wk["played"].any()
    assert cut["teams"].filter((pl.col("season") == 2020) & (pl.col("week") > 5)).is_empty()


def test_plain_variant_ignores_participation(pl):
    data = planted(pl)
    flat = data["players"].with_columns(pl.lit(30.0).alias("snaps"), pl.lit(10.0).alias("routes"))
    prm = role.fit(data, [2019], "plain")
    a = role.project(data, prm)["role"]
    b = role.project({**data, "players": flat}, prm)["role"]
    assert np.allclose(a, b)
