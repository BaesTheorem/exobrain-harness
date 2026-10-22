"""net-gate closes an outage only when the link holds (bin/net-gate INVARIANTS)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "bin" / "net-gate"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("net_gate", str(GATE))
    spec = importlib.util.spec_from_loader("net_gate", loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOG_DIR", tmp_path)
    monkeypatch.setattr(mod, "STATE", tmp_path / "net-outage.json")
    monkeypatch.setattr(mod, "LOCK", tmp_path / "net-outage.lock")
    monkeypatch.setattr(mod, "STABLE_GAP", 0)
    monkeypatch.setenv("NET_GATE_NO_NOTIFY", "1")
    monkeypatch.setenv("NET_GATE_LABEL", "com.exobrain.test-job")
    calls: dict[str, list] = {"exec": [], "run": []}
    monkeypatch.setattr(mod.os, "execvp", lambda c, a: calls["exec"].append(a))
    monkeypatch.setattr(mod.subprocess, "run", lambda a, **k: calls["run"].append(a))
    setattr(mod, "calls", calls)  # test-only handle on the stubs
    return mod


def run(mod, monkeypatch, answers):
    seq = iter(answers)
    monkeypatch.setattr(mod, "once", lambda host: next(seq))
    monkeypatch.setattr(sys, "argv", ["net-gate", "--wait", "0", "--", "true"])
    return mod.main()


def open_outage(mod):
    mod.STATE.write_text(json.dumps(
        {"since": 1.0e12, "skips": {"com.exobrain.other": 2}, "alerted": True}))


def test_no_outage_runs_without_extra_probes(gate, monkeypatch):
    run(gate, monkeypatch, [True])
    assert gate.calls["exec"] == [["true"]]
    assert not gate.STATE.exists()


def test_unstable_link_keeps_outage_open(gate, monkeypatch):
    open_outage(gate)
    assert run(gate, monkeypatch, [True, True, False]) == 0
    assert gate.calls["exec"] == []
    assert gate.calls["run"] == []  # no kickstarts
    st = json.loads(gate.STATE.read_text())
    assert st["skips"]["com.exobrain.test-job"] == 1


def test_stable_link_closes_outage_and_reruns(gate, monkeypatch):
    open_outage(gate)
    run(gate, monkeypatch, [True, True, True])
    assert not gate.STATE.exists()
    assert any("kickstart" in a for a in gate.calls["run"])
    assert gate.calls["exec"] == [["true"]]
