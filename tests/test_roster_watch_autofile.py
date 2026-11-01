"""The roster-watch auto-file lane files only what Opus approves (2026-11-01).

The lane: a gated swap (free agent or waiver claim, any position) whose drop is
on our bench or IR, with QB, TE, K and D/ST swapped like for like. Every swap in
the lane goes to `opus_review` first, and only a FILE verdict reaches espn-tx.
The positive control files; each other case changes one condition and must not
reach espn-tx. No network, no model, no ESPN writes: subprocess.run, the review
and the rival lookup are stubbed.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))


@pytest.fixture()
def rw(monkeypatch):
    """The module plus what the stubbed espn-tx saw: `calls`, and `rc`, the
    exit code it returns (0 means the read-back verified)."""
    loader = importlib.machinery.SourceFileLoader("roster_watch", str(ROOT / "fantasy" / "bin" / "roster-watch"))
    spec = importlib.util.spec_from_loader("roster_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    box = SimpleNamespace(calls=[], rc=0, auto_file=mod.auto_file, log_race=mod.log_race,
                          verdict={"verdict": "FILE", "reason": "ok"}, reviewed=[])

    def fake_run(cmd, **kw):
        box.calls.append(cmd)
        return SimpleNamespace(returncode=box.rc, stdout='{"verified": true}', stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "rivals_needing", lambda pos: ["GEB"] if pos in ("D/ST", "K") else [])

    def fake_review(ev):
        box.reviewed.append(ev)
        return box.verdict

    monkeypatch.setattr(mod, "opus_review", fake_review)
    box.mod = mod
    return box


BENCH = {"Rams D/ST": "D/ST", "Wil Lutz": "K", "Josh Downs": "WR", "RJ Harvey": "RB", "Deshaun Watson": "QB"}
SWAP = {"kind": "swap_gate", "add": "Titans D/ST", "add_pos": "D/ST", "avail": "FA", "drop": "Rams D/ST",
        "drop_pos": "D/ST", "gain": 27.3}


def test_positive_control_files_through_espn_tx(rw):
    out = rw.auto_file(dict(SWAP), BENCH)
    assert out and out["verified"] is True and out["rivals"] == ["GEB"]
    assert len(rw.calls) == 1
    cmd = rw.calls[0]
    assert cmd[1].endswith("espn-tx") and cmd[2:] == ["claim", "--fa", "Titans D/ST", "--drop", "Rams D/ST"]


def test_skill_swap_files_after_review(rw):
    ev = {"kind": "swap_gate", "add": "Treylon Burks", "add_pos": "WR", "avail": "FA", "drop": "RJ Harvey",
          "drop_pos": "RB", "gain": 316.5, "gate": 49.7}
    out = rw.auto_file(ev, BENCH)
    assert out and out["verified"] is True and len(rw.reviewed) == 1
    assert rw.calls[0][2:] == ["claim", "--fa", "Treylon Burks", "--drop", "RJ Harvey"]


def test_waiver_claim_files_without_fa_flag(rw):
    out = rw.auto_file({**SWAP, "avail": "WVR", "add": "Packers D/ST"}, BENCH)
    assert out and out["verified"] is True
    assert rw.calls[0][2:] == ["claim", "Packers D/ST", "--drop", "Rams D/ST"]


@pytest.mark.parametrize("verdict", [
    {"verdict": "HOLD", "reason": "Harvey is back next week"},
    {"verdict": "maybe", "reason": "?"},
])
def test_review_hold_never_files(rw, verdict):
    rw.verdict = verdict
    out = rw.auto_file(dict(SWAP), BENCH)
    assert out and out["held"] is True and out["verified"] is False
    assert rw.calls == []


@pytest.mark.parametrize("change", [
    {"avail": "BE"},                                           # a lineup move, not a swap
    {"drop": "Browns D/ST"},                                   # not on our bench (a starter, or spent in a pending claim)
    {"add": "Chase McLaughlin", "add_pos": "K"},               # K add for a D/ST drop: wrong position
    {"add": "Michael Penix Jr.", "add_pos": "QB", "drop": "Josh Downs", "drop_pos": "WR"},  # never a second QB
    {"add": "Treylon Burks", "add_pos": "WR", "drop": "Deshaun Watson", "drop_pos": "QB"},  # QB slot swaps like for like
])
def test_outside_the_lane_never_files_or_reviews(rw, change):
    assert rw.auto_file({**SWAP, **change}, BENCH) is None
    assert rw.calls == [] and rw.reviewed == []


def test_no_rival_still_files(rw, monkeypatch):
    monkeypatch.setattr(rw.mod, "rivals_needing", lambda pos: [])
    out = rw.auto_file(dict(SWAP), BENCH)
    assert out and out["verified"] is True


def test_parse_verdict_takes_last_json_line(rw):
    text = 'thinking {"verdict": "HOLD", "reason": "draft"}\nfinal\n{"verdict": "FILE", "reason": "clear upgrade"}'
    assert rw.mod.parse_verdict(text) == {"verdict": "FILE", "reason": "clear upgrade"}
    assert rw.mod.parse_verdict("no json here")["verdict"] == "HOLD"


def test_stream_event_uses_its_slot_and_drop(rw):
    ev = {"kind": "stream_gate", "slot": "K", "add": "Chase McLaughlin", "avail": "FA", "drop": "Wil Lutz",
          "ours": "Wil Lutz", "why": "offense implied 6+ higher"}
    assert rw.auto_file(ev, BENCH)["verified"] is True
    assert rw.calls[0][2:] == ["claim", "--fa", "Chase McLaughlin", "--drop", "Wil Lutz"]


def test_unverified_write_is_reported_as_not_done(rw):
    rw.rc = 1
    out = rw.auto_file(dict(SWAP), BENCH)
    assert out and out["verified"] is False


def test_every_free_agent_banner_is_logged(rw, tmp_path):
    path = tmp_path / "fa-races.jsonl"
    rw.log_race(path, {**SWAP, "filed": {"verified": True, "rivals": ["GEB"]}}, "2026-10-22 14:00")
    rw.log_race(path, {**SWAP, "add": "Ryan Flournoy", "add_pos": "WR"}, "2026-10-22 14:30")
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert [(r["add"], r["filed"]) for r in rows] == [("Titans D/ST", True), ("Ryan Flournoy", False)]
