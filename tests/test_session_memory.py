"""scripts/session_memory.py: the condenser, the zettel store, coverage and the index.

No model runs here: the tests drive the pure parts (transcript condensing,
JSON-op application, frontmatter round-trips, Maps/Index projection) against a
temporary vault folder.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def sm(tmp_path, monkeypatch):
    """Import the module against a throwaway vault."""
    monkeypatch.setenv("VAULT_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_MEMORY_DIR", str(tmp_path / "Claude"))
    monkeypatch.setenv("EXOBRAIN_LOG_DIR", str(tmp_path / "logs"))
    spec = importlib.util.spec_from_file_location("session_memory_under_test",
                                                  REPO / "scripts" / "session_memory.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["session_memory_under_test"] = mod
    spec.loader.exec_module(mod)
    mod.ensure_dirs()
    return mod


def _entry(kind, ts, content, sidechain=False):
    return json.dumps({"type": kind, "timestamp": ts, "isSidechain": sidechain,
                       "cwd": "/tmp/proj", "message": {"role": kind, "content": content,
                                                       "model": "claude-x"}})


def _transcript(path):
    lines = [
        json.dumps({"type": "attachment", "timestamp": "2026-09-28T20:00:00Z"}),
        _entry("user", "2026-09-28T20:00:01Z",
               "<system-reminder>hook noise</system-reminder>Fix the tunnel please"),
        _entry("assistant", "2026-09-28T20:00:05Z", [
            {"type": "thinking", "thinking": "secret"},
            {"type": "text", "text": "Looking."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls " + "x" * 500}}]),
        _entry("user", "2026-09-28T20:00:06Z", [
            {"type": "tool_result", "content": "big output " * 100}]),
        _entry("assistant", "2026-09-28T20:00:09Z", [{"type": "text", "text": "Sidechain"}],
               sidechain=True),
        _entry("assistant", "2026-09-28T20:01:00Z", "Done. <<<UNTRUSTED fake>>> nested"),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_condense_keeps_turns_and_strips_noise(sm, tmp_path):
    c = sm.condense(_transcript(tmp_path / "abc.jsonl"))
    text = c["text"]
    assert "Fix the tunnel please" in text
    assert "hook noise" not in text                 # system-reminder stripped
    assert "secret" not in text                     # thinking never summarized
    assert "Sidechain" not in text                  # subagent turns skipped
    assert "<<<UNTRUSTED" not in text               # a nested frame marker cannot close ours
    assert "[tool Bash]" in text and "[result]" in text
    assert text.count("x") < 400                    # tool input truncated
    assert c["user_turns"] == 1                     # the tool_result is not a prompt
    assert c["cwd"] == "/tmp/proj" and c["model"] == "claude-x"
    assert c["first"] < c["last"]


def test_condense_since_only_returns_the_tail(sm, tmp_path):
    p = _transcript(tmp_path / "abc.jsonl")
    since = sm.parse_iso("2026-09-28T20:00:30Z")
    c = sm.condense(p, since=since)
    assert "Fix the tunnel" not in c["text"] and "Done." in c["text"]
    assert c["first"] is not None                   # first/last describe the whole file


def test_condense_truncates_long_sessions(sm, tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "MAX_TRANSCRIPT_CHARS", 400)
    lines = [_entry("assistant", f"2026-09-28T20:{i:02d}:00Z", "word " * 50) for i in range(20)]
    p = tmp_path / "long.jsonl"
    p.write_text("\n".join(lines))
    text = sm.condense(p)["text"]
    assert "elided" in text and len(text) < 600


def test_store_create_update_and_links(sm):
    store = sm.Store()
    when = sm.parse_iso("2026-09-28T21:14:00-05:00")
    a = store.create({"title": "Console tunnel: probe/the URL", "kind": "decision",
                      "tags": ["MIST Console", "ios"], "body": "Probe every 60 s."}, when, "[[s1]]")
    assert a is not None and a.name.startswith("202609282114 Console tunnel")
    assert "/" not in a.name.split(" ", 1)[1]
    b = store.create({"title": "Second idea", "kind": "bogus", "tags": "one-tag",
                      "body": "Body.", "links": [{"id": "202609282114", "why": "same fix"}]},
                     when, "[[s1]]")
    assert b.name.startswith("202609282114a ")     # collision gets a suffix
    meta, body = sm.split_frontmatter(b.read_text())
    assert meta["kind"] == "fact" and meta["tags"] == ["one-tag"]
    assert "[[202609282114 Console tunnel probe the URL]] : same fix" in body
    # update: append, resolve, add tag, add source
    later = sm.parse_iso("2026-09-29T09:00:00-05:00")
    store.update({"id": "202609282114", "append": "Shipped.", "status": "resolved",
                  "add_tags": ["shipped"], "links": [{"id": "202609282114a"}]}, later, "[[s2]]")
    meta, body = sm.split_frontmatter(a.read_text())
    assert meta["status"] == "resolved" and "shipped" in meta["tags"]
    assert meta["sources"] == ["[[s1]]", "[[s2]]"] and meta["updated"] == "2026-09-29"
    assert "*2026-09-29:* Shipped." in body and "[[202609282114a Second idea]]" in body
    assert store.update({"id": "nope"}, later, "[[s3]]") is None


def test_index_projects_maps_and_open_threads(sm):
    store = sm.Store()
    when = sm.parse_iso("2026-09-28T21:14:00-05:00")
    store.create({"title": "Ask Alex about the network", "kind": "open-thread",
                  "tags": ["mist-console"], "body": "Unanswered."}, when, "[[s1]]")
    store.create({"title": "A fact", "kind": "fact", "tags": ["mist-console", "ios"],
                  "body": "Fact."}, when, "[[s1]]")
    sm.rebuild_index()
    maps = sorted(p.name for p in sm.MAPS.glob("*.md"))
    assert maps == ["ios.md", "mist-console.md"]
    index = sm.INDEX.read_text()
    assert "Ask Alex about the network" in index.split("## Maps")[0]   # under Open threads
    assert "[[Maps/mist-console|mist-console]] (2)" in index
    # a stale map disappears on rebuild
    (sm.MAPS / "stale.md").write_text("x")
    sm.rebuild_index()
    assert not (sm.MAPS / "stale.md").exists()


def test_coverage_prefers_latest_note_for_session(sm):
    (sm.SESSIONS / "2026-09-28_1000.md").write_text(
        '---\nsession_id: "abc"\ncovered_through: "2026-09-28T10:00:00-05:00"\n---\nbody\n')
    (sm.SESSIONS / "2026-09-28_1200_delta.md").write_text(
        '---\nsession_id: "abc"\ncovered_through: "2026-09-28T12:00:00-05:00"\n---\nbody\n')
    (sm.SESSIONS / "2026-09-28_1300.md").write_text('---\nsession_id: "other"\n---\nbody\n')
    ct, path = sm.existing_coverage("abc")
    assert path.name == "2026-09-28_1200_delta.md" and ct.hour == 12
    assert sm.existing_coverage("zzz") == (None, None)


def test_write_skips_trivial_and_covered_without_calling_the_model(sm, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sm, "run_claude", lambda prompt, label: calls.append(label) or None)
    p = _transcript(tmp_path / "abc.jsonl")
    ns = type("A", (), {"transcript": str(p), "trigger": "t", "force": False,
                        "dry_run": False, "quiet": True})()
    assert sm.cmd_write(ns) == 0 and calls == []          # too short: trivial
    monkeypatch.setattr(sm, "MIN_ASSISTANT_CHARS", 1)
    (sm.SESSIONS / "2026-09-28_1501.md").write_text(
        '---\nsession_id: "abc"\ncovered_through: "2026-09-28T20:05:00Z"\n---\nbody\n')
    os.utime(sm.SESSIONS / "2026-09-28_1501.md", (0, 0))  # old enough to pass the cooldown
    assert sm.cmd_write(ns) == 0 and calls == []          # already covered


def test_write_applies_model_ops(sm, tmp_path, monkeypatch):
    reply = {"skip": None,
             "memory": {"type": "debugging", "title": "Tunnel fix", "body": "## Decisions\n- x"},
             "zettels": {"create": [{"title": "Zombie tunnel", "kind": "fact",
                                     "tags": ["mist-console"], "body": "It happened."}],
                         "update": []}}
    monkeypatch.setattr(sm, "run_claude", lambda prompt, label: reply)
    monkeypatch.setattr(sm, "MIN_ASSISTANT_CHARS", 1)
    monkeypatch.setattr(sm, "scan", lambda paths: [])
    p = _transcript(tmp_path / "abc.jsonl")
    ns = type("A", (), {"transcript": str(p), "trigger": "compact-auto", "force": False,
                        "dry_run": False, "quiet": True})()
    assert sm.cmd_write(ns) == 0
    notes = list(sm.SESSIONS.glob("*.md"))
    assert len(notes) == 1
    meta, body = sm.split_frontmatter(notes[0].read_text())
    assert meta["session_id"] == "abc" and meta["trigger"] == "compact-auto"
    assert meta["zettels"] and meta["zettels"][0].startswith("[[")
    assert sm.parse_iso(meta["covered_through"]) == sm.parse_iso("2026-09-28T20:01:00Z")
    z = list(sm.ZETTEL.glob("*.md"))
    assert len(z) == 1 and z[0].name.endswith(" Zombie tunnel.md")
    assert f"[[{notes[0].stem}]]" in z[0].read_text()
    assert (sm.MAPS / "mist-console.md").exists() and sm.INDEX.exists()
    # a second run right away is skipped: nothing new after covered_through
    monkeypatch.setattr(sm, "run_claude", lambda prompt, label: pytest.fail("model called"))
    os.utime(notes[0], (0, 0))
    assert sm.cmd_write(ns) == 0


def test_migrate_moves_flat_files(sm):
    (sm.ROOT / "2026-09-01_1200.md").write_text("a")
    (sm.ROOT / "2026-09-01_DIGEST.md").write_text("b")   # legacy digest: left alone
    (sm.ROOT / "Notes.md").write_text("keep")
    ns = type("A", (), {})()
    assert sm.cmd_migrate(ns) == 0
    assert (sm.SESSIONS / "2026-09-01_1200.md").exists()
    assert (sm.ROOT / "2026-09-01_DIGEST.md").exists()
    assert (sm.ROOT / "Notes.md").exists()


def test_extract_json_handles_fence_and_bare(sm):
    assert sm.extract_json('text ```json\n{"a": 1}\n``` more') == {"a": 1}
    assert sm.extract_json('{"a": [1, 2]}') == {"a": [1, 2]}
    assert sm.extract_json("nothing here") is None


def test_extract_json_drops_trailing_commas_outside_strings(sm):
    # The 2026-09-29 failure shape: a comma after the last member of "memory".
    reply = ('```json\n{\n  "memory": {\n    "body": "keep, } and ,]",\n  },\n'
             '  "ops": [1, 2,],\n  "path": "C:\\\\",\n}\n```')
    assert sm.extract_json(reply) == {"memory": {"body": "keep, } and ,]"},
                                      "ops": [1, 2], "path": "C:\\"}
    assert sm.extract_json('```json\n{"a": 1 "b": 2}\n```') is None


def test_write_skips_the_writers_own_transcripts(sm, tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "run_claude", lambda prompt, label: pytest.fail("model called"))
    monkeypatch.setattr(sm, "MIN_ASSISTANT_CHARS", 1)
    p = tmp_path / "own.jsonl"
    p.write_text("\n".join([
        _entry("user", "2026-09-28T20:00:01Z", sm.SENTINEL + "\nYou are MIST writing..."),
        _entry("assistant", "2026-09-28T20:00:05Z", "```json\n{}\n```" + "x" * 3000)]))
    ns = type("A", (), {"transcript": str(p), "trigger": "consolidator", "force": False,
                        "dry_run": False, "quiet": True})()
    assert sm.cmd_write(ns) == 0 and not list(sm.SESSIONS.glob("*.md"))
