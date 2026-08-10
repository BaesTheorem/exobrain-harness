"""Characterization tests for discord/discord-digest-fetch.py message parsing.

That script is gitignored (it embeds a username-to-name map), so these tests
skip on a fresh clone and run on the machine that has it. Fixtures use only
synthetic usernames.
"""

import pytest

from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("discord/discord-digest-fetch.py"),
    reason="discord-digest-fetch.py is local-only (gitignored)",
)


@pytest.fixture(scope="module")
def dd():
    return load_script("discord/discord-digest-fetch.py")


def make_msg(**overrides):
    msg = {
        "id": "111222333",
        "author": {"id": "999", "username": "synthetic_user", "global_name": "Synth"},
        "content": "anyone up for trivia thursday?",
        "timestamp": "2026-08-10T17:00:00.000000+00:00",
        "attachments": [],
        "mentions": [],
    }
    msg.update(overrides)
    return msg


def test_parse_message_shape(dd):
    out = dd.parse_message(make_msg())
    assert out["id"] == "111222333"
    assert out["author"] == "Synth"  # global_name wins for unmapped users
    assert out["is_alex"] is False
    assert out["content"] == "anyone up for trivia thursday?"
    assert out["attachments"] == 0
    assert out["mentions_alex"] is False
    assert out["reply_to"] is None


def test_alex_detection_by_id(dd):
    out = dd.parse_message(make_msg(author={"id": dd.ALEX_ID, "username": "x"}))
    assert out["is_alex"] is True


def test_mentions_alex(dd):
    out = dd.parse_message(make_msg(mentions=[{"id": dd.ALEX_ID}]))
    assert out["mentions_alex"] is True


def test_reply_threading(dd):
    out = dd.parse_message(make_msg(referenced_message={"id": "444"}))
    assert out["reply_to"] == "444"


def test_username_fallback_when_no_global_name(dd):
    out = dd.parse_message(make_msg(author={"id": "999", "username": "synthetic_user"}))
    assert out["author"] == "synthetic_user"
