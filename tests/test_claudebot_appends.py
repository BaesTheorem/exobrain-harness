"""claude-bot standing per-person appends (staged.py): a line on every reply to one user."""

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/staged.py"), reason="claude-bot not present"
)


def _st():
    return load_script("claude-bot/staged.py")


def test_set_and_apply_by_username_case_insensitive(tmp_path):
    st = _st()
    store = tmp_path / "appends.json"
    st.set_append("@Some_User", "tag line", store=store)
    assert st.with_append("hello  \n", "some_user", store=store) == "hello\ntag line"
    assert st.with_append("hello", "SOME_USER", store=store) == "hello\ntag line"
    assert st.with_append("hello", "other", store=store) == "hello"
    assert st.with_append("hello", None, store=store) == "hello"


def test_empty_reply_becomes_the_line(tmp_path):
    st = _st()
    store = tmp_path / "appends.json"
    st.set_append("u", "line", store=store)
    assert st.with_append("", "u", store=store) == "line"


def test_replace_remove_list(tmp_path):
    st = _st()
    store = tmp_path / "appends.json"
    st.set_append("u", "one", store=store)
    st.set_append("u", "two", store=store)
    st.set_append("v", "three", store=store)
    assert st.list_appends(store=store) == {"u": "two", "v": "three"}
    assert st.remove_append("U", store=store) is True
    assert st.remove_append("u", store=store) is False
    assert st.list_appends(store=store) == {"v": "three"}


def test_rejects_blank_and_survives_garbage(tmp_path):
    st = _st()
    store = tmp_path / "appends.json"
    with pytest.raises(ValueError):
        st.set_append("u", "  ", store=store)
    store.write_text("[1, 2]")
    assert st.list_appends(store=store) == {}
    assert st.with_append("x", "u", store=store) == "x"
