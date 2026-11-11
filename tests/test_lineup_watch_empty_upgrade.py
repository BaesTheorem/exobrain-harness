"""lineup-watch fills an empty slot listed as a swap (2026-11-07).

`espn check` lists an empty slot as a swap whose starter is "(empty)". The
upgrade path must move the bench player into that slot, not look up a player
named "(empty)". Control: a normal swap still calls swap(). Writes are stubbed.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))


def load(monkeypatch, calls):
    loader = importlib.machinery.SourceFileLoader("lineup_watch_t", str(ROOT / "fantasy" / "bin" / "lineup-watch"))
    spec = importlib.util.spec_from_loader("lineup_watch_t", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    import espncli.client as c
    import espncli.tx as tx

    class Api:
        def resolve_one(self, name):
            if name == "(empty)":
                raise LookupError(name)
            return {"id": name}

    class W:
        def __init__(self, api):
            pass

        def move(self, pid, slot):
            calls.append(("move", pid, slot))
            return {"verified": True}

        def swap(self, a, b):
            calls.append(("swap", a, b))
            return {"verified": True}

        def lineup(self, moves):
            calls.append(("lineup", moves))
            return {"verified": True}

        def exchange(self, a, b):
            calls.append(("exchange", a, b))
            return {"verified": True}

    monkeypatch.setattr(c, "Espn", Api)
    monkeypatch.setattr(tx, "EspnWriter", W)
    return mod


def test_empty_slot_upgrade_moves(monkeypatch):
    calls: list = []
    mod = load(monkeypatch, calls)
    s = {"bench": "Malik Washington", "starter": "(empty)", "slot": "WR", "d_net": 16.3}
    assert mod.apply_upgrade(s, dry=False)
    assert calls and calls[0][0] == "move" and calls[0][1] == "Malik Washington"


def test_normal_upgrade_swaps(monkeypatch):
    calls: list = []
    mod = load(monkeypatch, calls)
    s = {"bench": "A", "starter": "B", "slot": "RB", "d_net": 2.2}
    assert mod.apply_upgrade(s, dry=False)
    assert calls == [("swap", "A", "B")]


def test_an_empty_slot_filled_through_flex_is_one_transaction(monkeypatch):
    """2026-11-11: an empty RB slot, a bench WR, and an RB in FLEX who takes the slot."""
    calls: list = []
    mod = load(monkeypatch, calls)
    s = {"bench": "Bench WR", "starter": "(empty)", "slot": "FLEX", "via": "Flex RB", "via_slot": "RB", "d_net": 12.0}
    done = mod.apply_upgrade(s, dry=False)
    assert done and "Flex RB to RB" in done
    assert calls == [("lineup", [("Flex RB", 2), ("Bench WR", 23)])], "the FLEX player first, then the bench player"


def test_a_swap_through_flex_is_left_to_the_write_lane(monkeypatch):
    calls: list = []
    mod = load(monkeypatch, calls)
    s = {"bench": "Bench WR", "starter": "Weak RB", "slot": "FLEX", "via": "Flex RB", "via_slot": "RB", "d_net": 3.0}
    assert "Flex RB to RB" in mod.apply_upgrade(s, dry=False)
    assert calls == [("swap", "Bench WR", "Weak RB")]


def test_the_slot_order_is_an_exchange_and_a_dry_run_writes_nothing(monkeypatch):
    calls: list = []
    mod = load(monkeypatch, calls)
    order = {"to_flex": "Monday WR", "to_flex_id": 5, "from_flex": "Thursday WR", "from_flex_id": 6, "slot": "WR",
             "late_kick": "Mon 7:15 PM", "flex_kick": "Thu 7:15 PM"}
    assert mod.apply_order(order, dry=True).startswith("DRY-RUN") and calls == []
    done = mod.apply_order(order, dry=False)
    assert done and done.endswith("(verified)") and calls == [("exchange", 5, 6)]
