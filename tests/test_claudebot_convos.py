"""claude-bot chatter_log: DB.log_chat writes a row, the FTS index follows it,
and bin/discord-convos reads it back with its filters."""

import json
import os
import subprocess
import sys

import pytest
from conftest import REPO, load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/db.py"), reason="claude-bot not present"
)
CLI = REPO / "claude-bot" / "bin" / "discord-convos"


def _seed(path):
    db = load_script("claude-bot/db.py").DB(path)
    base = dict(guild="G", channel="general", channel_id=1, user_id=2)
    db.log_chat(role="user", content="what is a pancake", guest=True, private=False,
                username="friend", display_name="Friend", **base)
    db.log_chat(role="assistant", content="a flat cake", guest=True, private=False,
                username="friend", display_name="Friend", model="m", **base)
    db.log_chat(role="user", content="owner turn", guest=False, private=True,
                username="owner", display_name="Owner", **base)
    return db


def _run(path, *args):
    env = {**os.environ, "DISCORD_CONVOS_DB": str(path)}
    out = subprocess.run([sys.executable, str(CLI), *args], env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_log_and_read_back(tmp_path):
    path = tmp_path / "bot.db"
    _seed(path)
    text = _run(path)
    assert "Friend (@friend) [guest]" in text and "MIST [m]" in text and "owner turn" in text


def test_guest_filter_and_search(tmp_path):
    path = tmp_path / "bot.db"
    _seed(path)
    rows = json.loads(_run(path, "--guest", "--json"))
    assert {r["username"] for r in rows} == {"friend"}
    rows = json.loads(_run(path, "--search", "pancake", "--json"))
    assert [r["content"] for r in rows] == ["what is a pancake"]


def test_old_window_is_empty(tmp_path):
    path = tmp_path / "bot.db"
    _seed(path)
    assert "no turns" in _run(path, "--since", "2000-01-01T00:00:00", "--user", "nobody")


RECORD = REPO / "claude-bot" / "bin" / "discord-record"


def _record(path, text, *args):
    env = {**os.environ, "DISCORD_CONVOS_DB": str(path)}
    return subprocess.run([sys.executable, str(RECORD), "--channel", "1", *args],
                          input=text, env=env, capture_output=True, text=True)


def test_outbound_reuses_known_channel_and_hides_notify(tmp_path):
    path = tmp_path / "bot.db"
    _seed(path)  # channel 1 is already named, so no Discord lookup happens
    assert _record(path, "hello from MIST", "--source", "discord-send.py").returncode == 0
    assert _record(path, "watcher alert", "--source", "awair", "--notify").returncode == 0
    rows = json.loads(_run(path, "--json"))
    out = [r for r in rows if r["role"] == "outbound"]
    assert [(r["content"], r["channel"], r["note"]) for r in out] == [
        ("hello from MIST", "general", "via discord-send.py")]
    rows = json.loads(_run(path, "--json", "--notify"))
    assert "watcher alert" in [r["content"] for r in rows]


def test_record_never_fails_the_sender(tmp_path):
    bad = _record(tmp_path / "missing-dir" / "bot.db", "x")
    assert bad.returncode == 0
    assert _record(tmp_path / "bot.db", "x", "--message-id", "not-a-number").returncode == 0
