"""The roster-watch auto-file lane files only what Alex approved (2026-10-22).

The lane: a free-agent K or D/ST that cleared the gate, for our bench K or
D/ST of the same position, when a rival has the same need. Everything else
must stay a banner for his tap. The positive control files; each other case
changes one condition and must not reach espn-tx. No network, no ESPN writes:
subprocess.run and the rival lookup are stubbed.
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
    box = SimpleNamespace(calls=[], rc=0, auto_file=mod.auto_file, log_race=mod.log_race)

    def fake_run(cmd, **kw):
        box.calls.append(cmd)
        return SimpleNamespace(returncode=box.rc, stdout='{"verified": true}', stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "rivals_needing", lambda pos: ["GEB"] if pos in ("D/ST", "K") else [])
    box.mod = mod
    return box


BENCH = {"Rams D/ST": "D/ST", "Wil Lutz": "K", "Josh Downs": "WR"}
SWAP = {"kind": "swap_gate", "add": "Titans D/ST", "add_pos": "D/ST", "avail": "FA", "drop": "Rams D/ST",
        "drop_pos": "D/ST", "gain": 27.3}


def test_positive_control_files_through_espn_tx(rw):
    out = rw.auto_file(dict(SWAP), BENCH)
    assert out and out["verified"] is True and out["rivals"] == ["GEB"]
    assert len(rw.calls) == 1
    cmd = rw.calls[0]
    assert cmd[1].endswith("espn-tx") and cmd[2:] == ["claim", "--fa", "Titans D/ST", "--drop", "Rams D/ST"]


@pytest.mark.parametrize("change", [
    {"avail": "WVR"},                                          # a waiver claim is not a race
    {"add": "Ryan Flournoy", "add_pos": "WR", "drop": "Josh Downs", "drop_pos": "WR"},   # skill players wait for Alex
    {"drop": "Browns D/ST"},                                   # not on our bench (a starter, or spent in a pending claim)
    {"add": "Chase McLaughlin", "add_pos": "K"},               # K add for a D/ST drop: wrong position
])
def test_outside_the_lane_never_files(rw, change):
    assert rw.auto_file({**SWAP, **change}, BENCH) is None
    assert rw.calls == []


def test_no_rival_with_the_need_is_no_race(rw, monkeypatch):
    monkeypatch.setattr(rw.mod, "rivals_needing", lambda pos: [])
    assert rw.auto_file(dict(SWAP), BENCH) is None
    assert rw.calls == []


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
