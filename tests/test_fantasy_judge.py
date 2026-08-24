"""Tests for the self-grading-loop fix: consensus judge, ledger, bias machinery.

The debias tests are the load-bearing ones: the correction is OFF by default
after a negative experiment, and if it is ever re-enabled, the band-mean and
strict-ordering properties are what keep it honest.
"""

import json

import pytest
from conftest import load_script

consensus = load_script("fantasy/consensus.py")
vor = load_script("fantasy/vor.py")
ledger = load_script("fantasy/ledger.py")


def test_consensus_norm_matches_grade_norm():
    n = consensus.norm
    assert n("Ka'imi Fairbairn") == n("Ka’imi Fairbairn")
    assert n("Brian Thomas Jr.") == n("Brian Thomas")
    assert n("A.J. Brown") == n("AJ Brown")


def test_dst_name_normalization():
    assert consensus.dst_name("Houston Texans") == "Texans D/ST"
    assert consensus.dst_name("denver broncos") == "Broncos D/ST"
    assert consensus.dst_name("Texans DST") == "Texans D/ST"
    assert consensus.dst_name("Not A Team") is None


def test_debias_off_by_default():
    # Negative experiment 2026-08-24: corrected board graded worse under the
    # independent judge, so the default strength must stay 0 until the ledger
    # (real season points) says otherwise.
    assert vor.BIAS_STRENGTH == 0.0
    curve = [300.0, 290.0, 280.0]
    assert vor.debias("RB", curve) == curve


def test_debias_band_mean_and_ordering(monkeypatch):
    monkeypatch.setattr(vor, "BIAS_STRENGTH", 1.0)
    # A gentle synthetic curve, steeper than the correction's decay.
    curve = [400.0 - 3.0 * i for i in range(40)]
    out = vor.debias("RB", curve)
    lo, hi, mean = vor.ELITE_BIAS["RB"]
    # Inside the band the correction is exactly the published statistic.
    shrink = [curve[i] - out[i] for i in range(len(curve))]
    band = shrink[lo - 1 : hi]
    assert all(s == pytest.approx(mean) for s in band)
    # It vanishes at replacement rank, so the baseline is untouched.
    repl = vor.REPLACEMENT["RB"]
    assert shrink[repl - 1] == pytest.approx(0.0)
    # Strictly decreasing: the Ringer's ordering survives even where the
    # correction is taller than the curve's slope.
    assert all(out[i] < out[i - 1] for i in range(1, len(out)))


def test_debias_strict_on_flat_curve(monkeypatch):
    monkeypatch.setattr(vor, "BIAS_STRENGTH", 1.0)
    # QB2-QB10 really do span ~30 points; a flat curve is the realistic case
    # where a naive clamp erased ordering.
    curve = [380.0] + [330.0 - 1.0 * i for i in range(20)]
    out = vor.debias("QB", curve)
    assert all(out[i] < out[i - 1] for i in range(1, len(out)))


def test_ledger_add_and_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "ledger.json")

    class A:
        a, b, claim, basis, date = "Player A", "Player B", "test claim", "", "2026-08-24"

    ledger.cmd_add(A)
    data = json.loads((tmp_path / "ledger.json").read_text())
    assert data["entries"][0]["a"] == "Player A"
    assert data["entries"][0]["status"] == "open"
    ledger.cmd_list(None)
    outp = capsys.readouterr().out
    assert "Player A > Player B" in outp


def test_ledger_settle_scores_sides(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "ledger.json")
    (tmp_path / "ledger.json").write_text(json.dumps({"entries": [
        {"id": 1, "date": "", "a": "Right Call", "b": "Other Guy",
         "claim": "", "basis": "", "status": "open"},
        {"id": 2, "date": "", "a": "Bad Call", "b": "Better Guy",
         "claim": "", "basis": "", "status": "open"},
    ]}))
    monkeypatch.setattr(ledger, "actual_points", lambda season=None: {
        "rightcall": 200.0, "otherguy": 150.0,
        "badcall": 90.0, "betterguy": 210.0,
    })
    ledger.cmd_settle(None)
    outp = capsys.readouterr().out
    assert "board right 1, wrong 1, pending 0" in outp
    data = json.loads((tmp_path / "ledger.json").read_text())
    assert data["entries"][0]["a_pts"] == 200.0


signoff = load_script("fantasy/signoff.py")


def _fixture_boards(tmp_path, monkeypatch):
    vor_data = {"players": {
        "bigreach": {"name": "Big Reach", "pos": "WR", "posRank": 10,
                     "vor": 50.0, "adp": 40.0},
        "agreed": {"name": "Agreed Guy", "pos": "WR", "posRank": 20,
                   "vor": 20.0, "adp": 80.0},
        "deeppass": {"name": "Deep Pass", "pos": "WR", "posRank": 90,
                     "vor": -40.0, "adp": 200.0},
    }}
    # Positional rank comes from ordering, so the fixture needs a full field:
    # filler WRs occupy every other slot and our three land at exactly the
    # ECR pos-ranks their ecr values name (30, 21, 80).
    ecr_data = {
        "bigreach": {"name": "Big Reach", "pos": "WR", "ecr": 30},
        "agreed": {"name": "Agreed Guy", "pos": "WR", "ecr": 21},
        "deeppass": {"name": "Deep Pass", "pos": "WR", "ecr": 80},
    }
    for i in range(1, 101):
        if i not in (30, 21, 80):
            ecr_data[f"filler{i}"] = {"name": f"Filler {i}", "pos": "WR", "ecr": i}
    (tmp_path / "vor.json").write_text(json.dumps(vor_data))
    (tmp_path / "ecr.json").write_text(json.dumps(ecr_data))
    monkeypatch.setattr(signoff, "VOR", tmp_path / "vor.json")
    monkeypatch.setattr(signoff, "ECR", tmp_path / "ecr.json")
    monkeypatch.setattr(signoff, "OVERRIDES", tmp_path / "overrides.json")


def test_signoff_flags_material_gaps_only(tmp_path, monkeypatch):
    _fixture_boards(tmp_path, monkeypatch)
    rows = signoff.divergences()
    names = [r["name"] for r in rows]
    # ECR pos-ranks derive from ecr ordering: bigreach WR2 vs ours WR10.
    assert "Big Reach" in names
    assert "Agreed Guy" not in names          # gap 1, immaterial
    assert "Deep Pass" not in names           # outside draftable range


def test_signoff_correct_roundtrip(tmp_path, monkeypatch, capsys):
    _fixture_boards(tmp_path, monkeypatch)

    class A:
        name, date = "Big Reach", "2026-08-24"

    signoff.cmd_correct(A)
    ov = json.loads((tmp_path / "overrides.json").read_text())
    assert ov["bigreach"]["action"] == "consensus"
    # status must now be clean (the one material divergence is signed)
    signoff.cmd_status(None)
    assert "all material divergences signed" in capsys.readouterr().out


def test_signoff_keep_registers_ledger_bet(tmp_path, monkeypatch, capsys):
    _fixture_boards(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(signoff.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))

    class A:
        name, thesis, vs, date = "Big Reach", "we believe", None, "2026-08-24"

    signoff.cmd_keep(A)
    ov = json.loads((tmp_path / "overrides.json").read_text())
    assert ov["bigreach"]["thesis"] == "we believe"
    assert calls and "ledger.py" in str(calls[0][1])
