"""claude-bot model/effort switching: catalog discovery, name normalization,
and the persisted settings the chatter module reads them from."""

import re

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/models.py"), reason="claude-bot not present"
)


def _models():
    return load_script("claude-bot/models.py")


def test_discover_models_parses_clean_aliases_only(tmp_path):
    m = _models()
    fake = tmp_path / "claude"
    fake.write_bytes(
        b"junk claude-opus-5 more claude-opus-4-8 claude-opus-5-20260401 "
        b"claude-sonnet-5 claude-haiku-4-5 claude-fable-5-1 claude-fable-5 "
        b"claude-opus-4-8-fast claude-opus-5[1m]"
    )
    found = m.discover_models(str(fake))
    # Families in ALIASES order, newest version first within each family;
    # dated and -fast snapshots are dropped.
    assert found == [
        "claude-fable-5-1", "claude-fable-5",
        "claude-opus-5", "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    ]


def test_discover_models_missing_binary_is_empty():
    m = _models()
    assert m.discover_models(None) == []
    assert m.discover_models("/nonexistent/claude") == []


def test_normalize_accepts_aliases_ids_and_1m(tmp_path):
    m = _models()
    fake = tmp_path / "claude"
    fake.write_bytes(b"claude-opus-5 claude-sonnet-5")
    cat = m.ModelCatalog(str(fake))
    assert cat.normalize("Opus") == "opus"
    assert cat.normalize("claude-opus-5") == "claude-opus-5"
    assert cat.normalize("claude-opus-5[1m]") == "claude-opus-5[1m]"
    assert cat.normalize("claude-opus-4-8") is None  # not in this binary
    assert cat.normalize("gpt-5") is None
    assert cat.normalize("") is None


def test_normalize_without_discovery_accepts_anything():
    m = _models()
    cat = m.ModelCatalog("/nonexistent/claude")
    assert cat.normalize("claude-whatever-9") == "claude-whatever-9"


def test_normalize_effort():
    m = _models()
    assert m.normalize_effort("XHIGH") == "xhigh"
    assert m.normalize_effort("auto") == "default"
    assert m.normalize_effort("turbo") is None
    assert set(m.EFFORT_LEVELS) == {"low", "medium", "high", "xhigh", "max"}


def test_effort_levels_match_cli_help():
    """The CLI is the source of truth for --effort choices; if it adds one,
    this fails and EFFORT_LEVELS gets updated."""
    m = _models()
    binpath = m.find_claude_bin()
    if not binpath:
        pytest.skip("claude CLI not installed")
    import subprocess

    out = subprocess.run([binpath, "--help"], capture_output=True, text=True, timeout=60).stdout
    match = re.search(r"--effort <level>.*?\(([a-z, ]+)\)", out, re.S)
    assert match, "could not find --effort choices in claude --help"
    assert tuple(x.strip() for x in match.group(1).split(",")) == m.EFFORT_LEVELS


def test_settings_roundtrip(tmp_path):
    db = load_script("claude-bot/db.py")
    d = db.DB(tmp_path / "t.db")
    assert d.get_setting("chatter.model", "fallback") == "fallback"
    d.set_setting("chatter.model", "claude-opus-5")
    d.set_setting("chatter.model", "claude-fable-5-1")  # upsert
    assert d.get_setting("chatter.model") == "claude-fable-5-1"
