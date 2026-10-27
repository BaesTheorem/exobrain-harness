"""Tests for the expert panel's writers' room: the revision loop, the vote tally and the board tools.

The loop tests replace run_round with a script that posts drafts and verdicts, so no model runs.
The board server test speaks JSON-RPC to a real board_server.py process.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
PANEL_DIR = REPO / "expert-panel"


def _load_panel() -> Any:
    spec = importlib.util.spec_from_file_location("expert_panel_under_test", PANEL_DIR / "panel.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["expert_panel_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


panel = _load_panel()
board = panel.board

VOTERS = ["chair", "a", "b"]


def _cfg(lo: int, hi: int) -> dict[str, Any]:
    agent = {"summary": "", "persona": ""}
    return {
        "title": "Test room", "model": "m", "draft_kind": "draft",
        "panelists": [{**agent, "handle": "a", "name": "A"}, {**agent, "handle": "b", "name": "B"}],
        "chair": {**agent, "handle": "chair", "name": "Chair"},
        "rounds": [{"id": "C", "label": "Cycle", "loop": {"min": lo, "max": hi}, "publish_kind": "final",
                    "steps": [{"id": "review", "who": VOTERS, "verdict": True, "prompt": "cycle $cycle of $max"},
                              {"id": "revise", "who": ["a"], "prompt": "cycle $cycle"}]}],
    }


@pytest.fixture
def room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str], dict[int, dict[str, bool]]]:
    """A run directory with one draft, and a fake run_round that votes from a per-cycle schedule."""
    monkeypatch.setattr(panel, "progress", lambda *a, **k: None)
    board.write_state(tmp_path, {"done": {}, "completed": [], "sessions": {}, "loops": {}})
    board.append_post(tmp_path, "b", "draft", "Draft one\nline two")
    calls: list[str] = []
    schedule: dict[int, dict[str, bool]] = {}

    def fake_run_round(run: Path, cfg: dict[str, Any], rnd: dict[str, Any]) -> int:
        calls.append(rnd["id"])
        state = board.read_state(run)
        state["round"] = rnd["id"]
        board.write_state(run, state)
        cycle = int(re.match(r"C(\d+)-", rnd["id"]).group(1))  # type: ignore[union-attr]
        if rnd.get("verdict"):
            draft = board.latest(board.read_posts(run), "draft")
            for voter, ok in schedule.get(cycle, {}).items():
                board.append_post(run, voter, "verdict", "v", data={"draft": draft["id"], "satisfied": ok,
                                                                  "must_change": "" if ok else "fix it"})
        else:
            board.append_post(run, "a", "draft", f"Draft after cycle {cycle}")
        state = board.read_state(run)
        state["completed"].append(rnd["id"])
        board.write_state(run, state)
        return len(rnd["who"])

    monkeypatch.setattr(panel, "run_round", fake_run_round)
    return tmp_path, calls, schedule


def test_loop_runs_the_minimum_cycles_then_stops_on_consensus(room):
    run, calls, schedule = room
    schedule.update({1: dict.fromkeys(VOTERS, True), 2: dict.fromkeys(VOTERS, True)})
    cfg = _cfg(lo=2, hi=8)
    outcome = panel.run_loop(run, cfg, cfg["rounds"][0])
    assert calls == ["C1-review", "C1-revise", "C2-review"]
    assert outcome["consensus"] and outcome["cycles"] == 2
    final = board.latest(board.read_posts(run), "final")
    assert final is not None and final["author"] == board.MODERATOR
    assert final["body"] == "Draft after cycle 1"  # word for word, the draft all three signed
    assert "C" in board.read_state(run)["completed"]


def test_one_dissent_keeps_the_loop_going_until_the_maximum(room):
    run, calls, schedule = room
    for c in range(1, 4):
        schedule[c] = {"chair": True, "a": True, "b": False}
    cfg = _cfg(lo=1, hi=3)
    outcome = panel.run_loop(run, cfg, cfg["rounds"][0])
    assert calls == ["C1-review", "C1-revise", "C2-review", "C2-revise", "C3-review"]
    assert not outcome["consensus"] and outcome["cycles"] == 3 and outcome["satisfied"] == 2
    assert outcome["blocking"] == {"b": "fix it"}
    assert "No consensus" in board.latest(board.read_posts(run), "final")["title"]


def test_a_vote_on_an_older_draft_does_not_count(tmp_path: Path):
    cfg = _cfg(lo=1, hi=1)
    board.write_state(tmp_path, {"round": "C1-review"})
    old = board.append_post(tmp_path, "a", "draft", "old")
    board.append_post(tmp_path, "b", "verdict", "v", data={"draft": old["id"], "satisfied": True})
    new = board.append_post(tmp_path, "a", "draft", "new")
    for voter in ("chair", "a"):
        board.append_post(tmp_path, voter, "verdict", "v", data={"draft": new["id"], "satisfied": True})
    step = panel.step_round(cfg["rounds"][0], cfg["rounds"][0]["steps"][0], 1)
    t = panel.tally(tmp_path, cfg, step)
    assert t["draft"] == new["id"] and t["satisfied"] == 2 and not t["consensus"]
    assert "not the latest" in t["blocking"]["b"]


def test_resume_rebuilds_the_loop_from_the_board(room):
    run, calls, schedule = room
    schedule.update({1: dict.fromkeys(VOTERS, True), 2: dict.fromkeys(VOTERS, True)})
    cfg = _cfg(lo=2, hi=8)
    first = panel.run_loop(run, cfg, cfg["rounds"][0])
    state = board.read_state(run)  # as if the process died before the loop was recorded
    state["completed"].remove("C")
    state["loops"] = {}
    board.write_state(run, state)
    calls.clear()
    again = panel.run_loop(run, cfg, cfg["rounds"][0])
    assert calls == []
    assert again == first
    assert sum(1 for p in board.read_posts(run) if p["kind"] == "final") == 1


def test_step_prompts_carry_the_cycle_number():
    cfg = _cfg(lo=2, hi=8)
    sub = panel.step_round(cfg["rounds"][0], cfg["rounds"][0]["steps"][0], 3)
    assert sub["id"] == "C3-review" and sub["prompt"] == "cycle 3 of 8" and sub["verdict"]


def _rpc(proc: subprocess.Popen[str], mid: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def _call(proc: subprocess.Popen[str], mid: int, name: str, args: dict[str, Any]) -> tuple[str, bool]:
    res = _rpc(proc, mid, "tools/call", {"name": name, "arguments": args})["result"]
    return res["content"][0]["text"], res["isError"]


def test_board_server_tools_drafts_and_verdicts(tmp_path: Path):
    hook = [sys.executable, "-c", "import sys; print(len(sys.stdin.read().split()), 'words')"]
    env = {"PANEL_RUN": str(tmp_path), "PANEL_AGENT": "a", "PANEL_CHAIR": "chair",
           "PANEL_TOOLS": json.dumps(["read_board", "post", "submit_verdict", "scan_text"]),
           "PANEL_KINDS": json.dumps(["draft", "critique"]), "PANEL_DRAFT_HOOK": json.dumps(hook),
           "PANEL_HOOK_LABEL": "Word count"}
    board.write_state(tmp_path, {"round": "R2"})
    proc = subprocess.Popen([sys.executable, str(PANEL_DIR / "board_server.py")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=env)
    try:
        _rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18"})
        tools = {t["name"] for t in _rpc(proc, 2, "tools/list")["result"]["tools"]}
        assert tools == {"read_board", "post", "submit_verdict", "scan_text"}
        assert _call(proc, 3, "submit_verdict", {"satisfied": True})[1]  # no draft yet
        text, err = _call(proc, 4, "post", {"kind": "draft", "title": "Draft 1", "body": "one two three"})
        assert not err and "Posted as #1" in text and "3 words" in text
        assert _call(proc, 5, "post", {"kind": "plan", "title": "x", "body": "y"})[1]  # kind not allowed
        assert _call(proc, 6, "submit_verdict", {"satisfied": False})[1]  # must_change required
        text, err = _call(proc, 7, "submit_verdict", {"satisfied": False, "must_change": "line 2"})
        assert not err and "not satisfied with draft #1" in text
        assert _call(proc, 8, "scan_text", {"text": "a b"})[0] == "2 words"
        board.write_state(tmp_path, {"round": "C1-review", "no_drafts": True})
        assert _call(proc, 9, "post", {"kind": "draft", "title": "x", "body": "y"})[1]  # review rounds refuse drafts
        text, _ = _call(proc, 10, "read_board", {"kind": "verdict,scan", "last": 1})
        assert "#3 | R2 | a [a] | verdict" in text and "| scan |" not in text
    finally:
        proc.stdin.close()  # type: ignore[union-attr]
        proc.wait(timeout=10)
    posts = board.read_posts(tmp_path)
    assert [p["kind"] for p in posts] == ["draft", "scan", "verdict"]
    assert posts[1]["author"] == board.MODERATOR and posts[1]["reply_to"] == 1
    assert posts[2]["data"] == {"draft": 1, "satisfied": False, "must_change": "line 2"}


def test_board_server_keeps_the_old_tool_list_without_new_settings(tmp_path: Path):
    env = {"PANEL_RUN": str(tmp_path), "PANEL_AGENT": "a"}
    proc = subprocess.Popen([sys.executable, str(PANEL_DIR / "board_server.py")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, env=env)
    try:
        tools = {t["name"] for t in _rpc(proc, 1, "tools/list")["result"]["tools"]}
    finally:
        proc.stdin.close()  # type: ignore[union-attr]
        proc.wait(timeout=10)
    assert tools == set(panel.BOARD_TOOLS)
