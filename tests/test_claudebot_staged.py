"""claude-bot staged replies (staged.py): one pre-arranged message, posted on cue."""

import json
import time

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/staged.py"), reason="claude-bot not present"
)


def _st():
    return load_script("claude-bot/staged.py")


def test_stage_then_take_consumes(tmp_path):
    st = _st()
    store = tmp_path / "staged.json"
    st.stage("hello", store=store)
    assert st.peek(store=store)["text"] == "hello"
    assert st.take(guild="Any", channel="general", store=store) == "hello"
    assert st.peek(store=store) is None
    assert not store.exists()


def test_room_filter_is_substring_case_insensitive(tmp_path):
    st = _st()
    store = tmp_path / "staged.json"
    st.stage("hi", guild="coven", channel="#General", store=store)
    assert st.take(guild="KC Coven", channel="random", store=store) is None
    assert store.exists(), "a miss must leave the entry in place"
    assert st.take(guild="KC Coven", channel="general", store=store) == "hi"


def test_expired_entry_is_dropped(tmp_path):
    st = _st()
    store = tmp_path / "staged.json"
    st.stage("late", ttl_hours=1, store=store)
    entry = json.loads(store.read_text())
    entry["expires_at"] = time.time() - 1
    store.write_text(json.dumps(entry))
    assert st.take(guild=None, channel=None, store=store) is None
    assert not store.exists()


def test_stage_replaces_and_rejects_empty(tmp_path):
    st = _st()
    store = tmp_path / "staged.json"
    st.stage("first", store=store)
    st.stage("second", store=store)
    assert st.peek(store=store)["text"] == "second"
    with pytest.raises(ValueError):
        st.stage("   ", store=store)
    assert st.clear(store=store) is True
    assert st.clear(store=store) is False


def test_garbage_file_reads_as_nothing(tmp_path):
    st = _st()
    store = tmp_path / "staged.json"
    store.write_text("{not json")
    assert st.peek(store=store) is None
