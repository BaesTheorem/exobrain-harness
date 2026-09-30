"""mist-notify's click routing (Alex, 2026-09-30): a banner click lands in a
Console chat. From inside a chat that is the chat itself; from a headless
sender it is a chat the Console seeds from the notification when tapped. The
caller's own link becomes a button unless --direct."""
import json
import os
import subprocess
from pathlib import Path

NOTIFY = Path(__file__).resolve().parent.parent / "mist-voice" / "bin" / "mist-notify"


def run(*args, sid=None, env=None):
    e = {k: v for k, v in os.environ.items() if k not in ("MIST_CONSOLE_SESSION", "MIST_NOTIFY_CONTEXT", "MIST_NOTIFY_SOURCE")}
    if sid:
        e["MIST_CONSOLE_SESSION"] = sid
    e.update(env or {})
    out = subprocess.run([str(NOTIFY), *args, "--dry-run"], capture_output=True, text=True, env=e, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_headless_default_opens_a_seeded_chat():
    spec = run("Inbox over five")
    assert spec["link"] == f"console:notif.{spec['nid']}"
    assert "source" not in spec


def test_headless_source_link_becomes_a_button():
    spec = run("Restock", "Watch", "Purr", "https://example.com/item",
               "--action", "Buy=https://example.com/buy")
    assert spec["link"].startswith("console:notif.")
    assert spec["source"] == "https://example.com/item"
    assert [a["label"] for a in spec["actions"]] == ["Buy", "Open link"]


def test_source_already_a_button_is_not_duplicated():
    spec = run("x", "T", "Purr", "https://a.example", "--action", "Go=https://a.example")
    assert [a["target"] for a in spec["actions"]] == ["https://a.example"]


def test_inside_a_chat_the_click_is_that_chat():
    spec = run("note done", "MIST", "Purr", "obsidian://open?vault=Exobrain&file=X", sid="s42")
    assert spec["link"] == "console:s42"
    assert spec["actions"][0]["label"] == "Open note"
    assert run("brief", "MIST", "Purr", "console", sid="s42")["link"] == "console:s42"


def test_direct_keeps_the_source_as_the_click():
    spec = run("pay now", "MIST", "Purr", "https://example.com/pay", "--direct")
    assert spec["link"] == "https://example.com/pay"
    assert "actions" not in spec


def test_console_bang_opts_out_of_the_upgrade():
    assert run("x", "MIST", "Purr", "console!", sid="s42")["link"] == "console"


def test_context_flags_and_env(tmp_path):
    ctx = tmp_path / "ctx.txt"
    ctx.write_text("line1\nline2\n")
    assert run("x", "--context-file", str(ctx))["context"] == "line1\nline2"
    assert run("x", "--context", "  hello ")["context"] == "hello"
    spec = run("x", env={"MIST_NOTIFY_CONTEXT": "from env", "MIST_NOTIFY_SOURCE": "routine morning-briefing"})
    assert spec["context"] == "from env"
    assert spec["origin"] == "routine morning-briefing"
    assert len(run("x", "--context", "a" * 5000)["context"]) == 4000


def test_rejected_source_is_recorded_not_opened():
    spec = run("x", "MIST", "Purr", "file:///etc/passwd")
    assert spec["link"].startswith("console:notif.")
    assert spec["rejected"][0]["link"] == "file:///etc/passwd"
    assert "actions" not in spec
