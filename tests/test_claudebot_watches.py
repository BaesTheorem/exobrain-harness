"""claude-bot pattern watches (watches.py): store, rolling window, !watch parser, verdicts."""

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/watches.py"), reason="claude-bot not present"
)


def _w():
    return load_script("claude-bot/watches.py")


# ---- store ----

def test_add_rule_for_remove(tmp_path):
    w = _w()
    store = tmp_path / "watches.json"
    rule = w.add("@Some_User", ask="q?", say="t", channel="#General", store=store)
    assert rule["count"] == 5 and rule["channel"] == "General"
    assert w.rule_for("some_user", "general-chat", store=store)["say"] == "t"
    assert w.rule_for("some_user", "random", store=store) is None
    assert w.rule_for("nobody", "general", store=store) is None
    assert w.remove("SOME_USER", store=store) is True
    assert w.remove("some_user", store=store) is False
    with pytest.raises(ValueError):
        w.add("u", ask="", say="t", store=store)
    with pytest.raises(ValueError):
        w.add("u", ask="q", say="t", count=0, store=store)


def test_garbage_store_reads_empty(tmp_path):
    w = _w()
    store = tmp_path / "watches.json"
    store.write_text("nope")
    assert w.load(store=store) == {}
    store.write_text('{"u": {"say": "only say"}}')
    assert w.load(store=store) == {}


# ---- rolling window + fire state ----

def test_window_prunes_and_counts():
    w = _w()
    win = w.Window()
    k = (1, 2)
    for t in (0, 10, 20, 30):
        win.add(k, t, 25)
    assert win.count(k) == 3  # t=0 fell out of the 25s window at t=30
    win.clear(k)
    assert win.count(k) == 0


def test_fire_state_gates_checks():
    w = _w()
    st = w.FireState()
    rule = {**w.DEFAULTS, "count": 5, "cooldown_min": 30, "recheck_every": 2}
    k = (1, 2)
    assert st.may_check(k, 4, rule, 0) is False          # under threshold
    assert st.may_check(k, 5, rule, 0) is True           # first check at threshold
    assert st.may_check(k, 6, rule, 1) is False          # a NO: wait for 2 more posts
    assert st.may_check(k, 7, rule, 2) is True
    st.fired(k, 100)
    assert st.may_check(k, 9, rule, 100 + 29 * 60) is False   # inside cooldown
    assert st.may_check(k, 9, rule, 100 + 31 * 60) is True


# ---- the !watch command ----

def test_parse_set_with_rate_and_quotes():
    w = _w()
    cmd = w.parse_command('!watch 5/30m ask "Is the author advocating X?" say "Doing it again?" cooldown 2h in #news')
    assert cmd == {"op": "set", "count": 5, "window_min": 30, "cooldown_min": 120, "channel": "news",
                   "ask": "Is the author advocating X?", "say": "Doing it again?"}


def test_parse_colon_forms_and_defaults():
    w = _w()
    cmd = w.parse_command('!nudge ask:"q?" say:"t"')
    assert cmd["ask"] == "q?" and cmd["say"] == "t" and cmd["count"] == 5 and cmd["window_min"] == 30
    assert w.parse_command("!watch off") == {"op": "off"}
    assert w.parse_command("!watch") == {"op": "show"}
    assert w.parse_command("!clippy status") == {"op": "show"}


@pytest.mark.parametrize("line", [
    '!watch ask "q?"',                      # no say
    '!watch 5/30m say "t"',                 # no ask
    '!watch ask "unbalanced say "t"',       # bad quotes
    '!watch 5/30m bogus ask "q" say "t"',   # stray token
    'hello ask "q" say "t"',                # not the command
])
def test_parse_rejects(line):
    w = _w()
    with pytest.raises(ValueError):
        w.parse_command(line)


def test_apply_command_is_self_only(tmp_path):
    w = _w()
    store = tmp_path / "watches.json"
    note = w.apply_command("Speaker", w.parse_command('!watch 3/10m ask "q?" say "t"'), store=store)
    assert note.startswith("watch set:") and "3+ times in 10 min" in note
    assert list(w.load(store=store)) == ["speaker"]
    assert w.apply_command("speaker", {"op": "show"}, store=store).startswith("your watch:")
    assert w.apply_command("speaker", {"op": "off"}, store=store) == "watch off."
    assert w.apply_command("speaker", {"op": "off"}, store=store) == "you had no watch set."


def test_extract_command_takes_only_a_trailing_line():
    w = _w()
    body, line = w.extract_command('sure thing :3\n`!watch 5/30m ask "q?" say "t"`\n')
    assert body == "sure thing :3" and line == '!watch 5/30m ask "q?" say "t"'
    body, line = w.extract_command("you could type !watch off to stop it\nok?")
    assert line is None and body.endswith("ok?")
    assert w.extract_command("") == ("", None)


def test_is_yes():
    w = _w()
    assert w.is_yes("YES\nthey keep saying it")
    assert w.is_yes("yes.")
    assert not w.is_yes("NO\nnothing of the sort")
    assert not w.is_yes("")
    assert not w.is_yes("Yes and no")
