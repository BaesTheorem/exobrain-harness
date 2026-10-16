"""scripts/zettel_maintain.py: the weekly Zettelkasten pass, with the model faked.

Each step gets a canned model reply and must apply only what validates against
the store (ids that exist, links that carry a reason, evidence that was shown).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def zm(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_MEMORY_DIR", str(tmp_path / "Claude"))
    monkeypatch.setenv("EXOBRAIN_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SESSION_MEMORY_EMBED_CACHE", str(tmp_path / "cache"))
    for name in ("session_memory", "zettel_maintain"):
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("zettel_maintain", REPO / "scripts" / "zettel_maintain.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["zettel_maintain"] = mod
    spec.loader.exec_module(mod)
    mod.sm.ensure_dirs()
    yield mod
    for name in ("session_memory", "zettel_maintain"):
        sys.modules.pop(name, None)


def _mk(zm, title, kind="fact", tags=("nest",), body="Body.", when="2026-09-01T10:00:00-05:00", links=()):
    store = zm.sm.Store()
    p = store.create({"title": title, "kind": kind, "tags": list(tags), "body": body,
                      "links": [{"id": z, "why": "test link"} for z in links]},
                     zm.sm.parse_iso(when), "[[s0]]")
    return p.stem.split(" ")[0]


def test_link_graph_counts_incoming(zm):
    a = _mk(zm, "First note")
    b = _mk(zm, "Second note", links=[a])
    out, inc = zm.link_graph(zm.sm.Store())
    assert out[b] == {a} and inc[a] == {b} and inc[b] == set()


def test_orphans_apply_only_valid_links(zm, monkeypatch):
    a = _mk(zm, "Orphan about thermostats")
    b = _mk(zm, "Neighbor about thermostats", when="2026-09-02T10:00:00-05:00")
    c = _mk(zm, "Unrelated", when="2026-09-03T10:00:00-05:00")
    nb = {a: [[b, 0.9]], b: [[a, 0.9]], c: []}
    reply = {"links": [{"from": b, "to": a, "why": "same thermostat schedule"},
                       {"from": c, "to": a, "why": "not a shown neighbor"},
                       {"from": b, "to": a, "why": ""}]}
    monkeypatch.setattr(zm, "ask", lambda *a_, **k: reply)
    ch = zm.Change(False)
    zm.step_orphans(zm.sm.Store(), nb, ch, "[[m]]", 10)
    store = zm.sm.Store()
    assert f"[[{a} Orphan about thermostats]] : same thermostat schedule" in store.notes[b]["body"]
    assert a not in store.notes[c]["body"]


def test_dupes_merge_supersedes_and_logs_miss(zm, monkeypatch):
    a = _mk(zm, "espn-tx pending prints nothing when empty")
    b = _mk(zm, "Empty espn-tx pending output means no queue", when="2026-09-05T10:00:00-05:00")
    nb = {a: [[b, 0.95]], b: [[a, 0.95]]}
    reply = {"pairs": [{"a": a, "b": b, "verdict": "duplicate", "keep": a, "merge": "Exit code is 0."}]}
    monkeypatch.setattr(zm, "ask", lambda *a_, **k: reply)
    ch = zm.Change(False)
    zm.step_dupes(zm.sm.Store(), nb, ch, "[[m]]", 10)
    store = zm.sm.Store()
    assert store.notes[b]["meta"]["status"] == "superseded"
    assert "Exit code is 0." in store.notes[a]["body"]
    assert f"Superseded by [[{a} " in store.notes[b]["body"]
    miss = [json.loads(ln) for ln in zm.MISS_LOG.read_text().splitlines()]
    assert miss[-1]["older"] == a and miss[-1]["newer"] == b


def test_threads_close_only_with_shown_evidence_and_escalate_rest(zm, monkeypatch):
    t1 = _mk(zm, "Ship the thermostat fix", kind="open-thread", body="Thermostat fix pending.")
    t2 = _mk(zm, "Pick a backup drive", kind="open-thread", body="Backup drive choice.",
             when="2026-09-01T11:00:00-05:00")
    done = _mk(zm, "Thermostat fix shipped", body="Thermostat fix shipped and verified.",
               when="2026-10-01T10:00:00-05:00")

    def fake(rules, payload, label):
        return {"threads": [{"id": t1, "verdict": "resolved", "evidence": f"[[{done} Thermostat fix shipped]]",
                             "why": "The fix shipped."},
                            {"id": t2, "verdict": "resolved", "evidence": "999999999999", "why": "guess"}]}
    monkeypatch.setattr(zm, "ask", fake)
    ch = zm.Change(False)
    zm.step_threads(zm.sm.Store(), ch, "[[m]]", 10)
    store = zm.sm.Store()
    assert store.notes[t1]["meta"]["status"] == "resolved"
    assert store.notes[t2]["meta"]["status"] == "active"       # evidence was not shown
    assert any(t2 in ln for ln in ch.alex)


def test_ticked_threads_close(zm):
    t = _mk(zm, "Decide on the bundle", kind="open-thread")
    (zm.sm.SESSIONS / "2026-10-01_0900_maintain.md").write_text(
        f"---\ntype: maintenance\n---\n## Open threads that need Alex\n- [x] [[{t} Decide on the bundle]]: x\n")
    ch = zm.Change(False)
    zm.close_ticked(zm.sm.Store(), ch, "[[m]]")
    assert zm.sm.Store().notes[t]["meta"]["status"] == "resolved"


def test_tags_merge_and_bucket_strip(zm, monkeypatch):
    a = _mk(zm, "One", tags=("console", "follow-up"))
    b = _mk(zm, "Two", tags=("mist-console",), when="2026-09-02T10:00:00-05:00")
    c = _mk(zm, "Three", tags=("follow-up",), when="2026-09-03T10:00:00-05:00")
    reply = {"merge": [{"from": ["console"], "into": "mist-console", "why": "same app"}], "buckets": ["follow-up"]}
    monkeypatch.setattr(zm, "ask", lambda *a_, **k: reply)
    zm.step_tags(zm.sm.Store(), zm.Change(False), "[[m]]")
    store = zm.sm.Store()
    assert store.notes[a]["meta"]["tags"] == ["mist-console"]
    assert store.notes[b]["meta"]["tags"] == ["mist-console"]
    assert store.notes[c]["meta"]["tags"] == ["follow-up"]     # its only tag stays
    assert zm.sm.bucket_tags() == {"follow-up"}
    assert "follow-up" not in store.tag_vocab()


def test_structure_note_keeps_only_member_ids(zm, monkeypatch):
    monkeypatch.setattr(zm, "STRUCTURE_MIN", 2)
    ids = [_mk(zm, f"Nest note {i}", when=f"2026-09-0{i + 1}T10:00:00-05:00") for i in range(3)]
    outsider = _mk(zm, "Other", tags=("fantasy",), when="2026-09-09T10:00:00-05:00")
    reply = {"overview": "Nest notes.", "entry": [ids[0], outsider],
             "sections": [{"heading": "Schedules", "summary": "S.", "items": [
                 {"id": ids[1], "gloss": "the schedule"}, {"id": outsider, "gloss": "x"}]}]}
    monkeypatch.setattr(zm, "ask", lambda *a_, **k: reply)
    zm.step_structure(zm.sm.Store(), zm.Change(False), False, 5)
    text = (zm.STRUCTURE / "nest.md").read_text()
    assert ids[0] in text and ids[1] in text and outsider not in text
    zm.sm.rebuild_index()
    assert "[[Structure/nest|nest]] (3)" in zm.sm.INDEX.read_text()
    assert not zm.structure_due("nest", 3, False)
