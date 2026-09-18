"""claude-bot thread auto-join: the use_threads value grammar, target
matching, validation text, and the guild-over-global preference rows."""

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/threadprefs.py"), reason="claude-bot not present"
)


def _tp():
    return load_script("claude-bot/threadprefs.py")


def test_normalize_bool_words():
    tp = _tp()
    assert tp.normalize("True") is True
    assert tp.normalize(" on ") is True
    assert tp.normalize("false") is False
    assert tp.normalize("0") is False


def test_normalize_targets_strip_mentions_and_hashes():
    tp = _tp()
    assert tp.normalize("<#123>, #general Events") == ["123", "general", "Events"]


def test_matches_by_channel_category_id_and_name():
    tp = _tp()
    assert tp.matches(True, 1, 2, "Events")
    assert not tp.matches(False, 1, 2, "Events")
    assert tp.matches(["1"], 1, 2, "Events")
    assert tp.matches(["2"], 1, 2, "Events")
    assert tp.matches(["events"], 1, 2, "Events")
    assert not tp.matches(["9", "other"], 1, 2, "Events")
    assert not tp.matches(["events"], 1, None, None)


def test_unknown_targets_and_suggestions():
    tp = _tp()
    cats = {"events": "Events", "alliances": "Alliances"}
    unknown = tp.unknown_targets(["10", "Evnts", "alliances"], {10}, {20}, cats)
    assert unknown == ["Evnts"]
    msg = tp.validation_message(unknown, cats, "KC")
    assert "did you mean" in msg and "`Events`" in msg
    # No close match -> list the known categories instead
    msg = tp.validation_message(["zzz"], cats, "KC")
    assert "Known categories in KC" in msg


def test_parse_key_and_user_mention():
    tp = _tp()
    assert tp.parse_key("123:use_threads") == (123, "use_threads")
    assert tp.parse_key("use_threads") == (None, "use_threads")
    assert tp.parse_key("a:b") == (None, "a:b")
    assert tp.parse_user_mention("<@!945577631133351947>") == 945577631133351947
    assert tp.parse_user_mention("945577631133351947") == 945577631133351947
    assert tp.parse_user_mention("true") is None
    assert tp.parse_user_mention("42") is None


def test_prefs_guild_overrides_global(tmp_path):
    db = load_script("claude-bot/db.py").DB(tmp_path / "t.db")
    db.set_pref(1, "use_threads", "true")                 # global
    assert db.get_pref(1, "use_threads", guild_id=7, allow_global=True) == "true"
    assert db.get_pref(1, "use_threads", guild_id=7) is None
    db.set_pref(1, "use_threads", "false", guild_id=7)    # guild row wins
    assert db.get_pref(1, "use_threads", guild_id=7, allow_global=True) == "false"
    assert sorted(db.users_with_pref("use_threads", 7)) == [1]
    assert db.users_with_pref("use_threads", 8) == [1]     # global row still counts
    assert db.del_pref(1, "use_threads", guild_id=7)
    assert not db.del_pref(1, "use_threads", guild_id=7)


def test_thread_summoned_marker(tmp_path):
    db = load_script("claude-bot/db.py").DB(tmp_path / "t.db")
    assert not db.thread_summoned(5)
    db.mark_thread_summoned(5, 7)
    db.mark_thread_summoned(5, 7)  # idempotent
    assert db.thread_summoned(5)


def test_old_user_prefs_shape_is_rebuilt(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE user_prefs (user_id INTEGER NOT NULL, key TEXT NOT NULL, "
              "value TEXT, PRIMARY KEY (user_id, key))")
    c.commit(); c.close()
    db = load_script("claude-bot/db.py").DB(path)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(user_prefs)")]
    assert "guild_id" in cols
