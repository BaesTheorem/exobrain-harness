"""Tests for zulip/usage_ledger.py: the abuse limits on MIST's Zulip listener.

The load-bearing cases: exempt users are never blocked, each limit blocks on
its own, and cost falls back sensibly when a session has no result line.
"""

import json
import time

from conftest import load_script

ledger = load_script("zulip/usage_ledger.py")

LIMITS = {
    "owner_user_id": 1, "exempt_user_ids": [1],
    "per_sender_per_hour": 2, "per_sender_per_day": 3,
    "per_sender_usd_per_day": 1.0, "global_usd_per_day": 2.0,
    "est_cost_per_session": 0.4,
}


def _result_log(tmp_path, name, cost=None, models=None):
    p = tmp_path / name
    row = {"type": "result", "subtype": "success"}
    if cost is not None:
        row["total_cost_usd"] = cost
    if models is not None:
        row["modelUsage"] = models
    p.write_text('{"type":"system"}\n' + json.dumps(row) + "\n")
    return str(p)


def test_exempt_user_is_never_blocked(tmp_path):
    now = time.time()
    spawns = [{"ts": now - 10, "sender_id": 1, "log": None} for _ in range(50)]
    assert ledger.check(1, spawns, now, LIMITS) == (True, "exempt")


def test_hourly_cap_blocks(tmp_path):
    now = time.time()
    spawns = [{"ts": now - 60 * i, "sender_id": 7, "log": None} for i in range(2)]
    ok, reason = ledger.check(7, spawns, now, LIMITS)
    assert not ok and "last hour" in reason


def test_daily_count_cap_blocks_after_hour_window_passes():
    now = time.time()
    day0 = ledger.day_start(now)
    spawns = [{"ts": max(day0 + 1, now - 7200 - 600 * i), "sender_id": 7, "log": None} for i in range(3)]
    ok, reason = ledger.check(7, spawns, now, LIMITS)
    assert not ok and ("today" in reason)


def test_sender_budget_uses_logged_cost(tmp_path):
    now = time.time()
    log = _result_log(tmp_path, "a.jsonl", cost=1.2)
    spawns = [{"ts": max(ledger.day_start(now) + 1, now - 7200), "sender_id": 7, "log": log}]
    ok, reason = ledger.check(7, spawns, now, LIMITS)
    assert not ok and "budget today" in reason


def test_global_budget_blocks_a_fresh_sender(tmp_path):
    now = time.time()
    log = _result_log(tmp_path, "b.jsonl", cost=2.5)
    spawns = [{"ts": max(ledger.day_start(now) + 1, now - 7200), "sender_id": 8, "log": log}]
    ok, reason = ledger.check(9, spawns, now, LIMITS)
    assert not ok and "org has used" in reason


def test_unfinished_session_counts_as_estimate(tmp_path):
    now = time.time()
    running = tmp_path / "running.jsonl"
    running.write_text('{"type":"system"}\n')
    spawns = [{"ts": now - 30, "sender_id": 7, "log": str(running)}]
    u = ledger.usage(spawns, now, LIMITS)
    assert u["senders"][7]["usd_day"] == 0.4


def test_cost_falls_back_to_model_usage(tmp_path):
    log = _result_log(tmp_path, "c.jsonl", models={"claude-opus-5": {"costUSD": 0.3}, "claude-haiku-4-5-20251001": {"costUSD": 0.05}})
    assert abs(ledger.session_cost(log) - 0.35) < 1e-9
    assert ledger.session_cost(str(tmp_path / "missing.jsonl")) is None


def test_record_and_read_roundtrip(tmp_path):
    path = tmp_path / "spawns.jsonl"
    ledger.record_spawn(7, "Jane's Claude", "claudes", "plans", "/tmp/x.jsonl", path=path, now=123.0)
    rows = ledger.read_spawns(path)
    assert rows == [{"ts": 123.0, "sender_id": 7, "sender_name": "Jane's Claude",
                     "stream": "claudes", "topic": "plans", "log": "/tmp/x.jsonl"}]


def test_allowed_when_under_every_limit():
    now = time.time()
    assert ledger.check(7, [], now, LIMITS) == (True, "ok")
