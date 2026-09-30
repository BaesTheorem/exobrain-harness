"""claude-bot natural-language model/effort switches (switchintent.py)."""

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/switchintent.py"), reason="claude-bot not present"
)


def _si():
    return load_script("claude-bot/switchintent.py")


@pytest.mark.parametrize("text,model", [
    ("switch to sonnet", "sonnet"),
    ("@MIST can you switch over to opus please", "opus"),
    ("swap models to haiku", "haiku"),
    ("go back to fable", "fable"),
    ("use opus 5.5 1m", "claude-opus-5-5[1m]"),
    ("use claude-fable-5-1 for this", "claude-fable-5-1"),
    ("change to Opus [1m]", "opus[1m]"),
    ("use sonnet.", "sonnet"),
])
def test_model_switches(text, model):
    assert _si().parse(text).model == model


@pytest.mark.parametrize("text", [
    "write me a haiku about cats",
    "I use sonnet for code, opus for prose",
    "can you use haiku to describe this",
    "the sonnet you wrote was great",
    "what's the difference between opus and sonnet?",
])
def test_model_non_switches(text):
    assert _si().parse(text).model is None


@pytest.mark.parametrize("text,effort,step", [
    ("max effort please", "max", 0),
    ("set your effort to high", "high", 0),
    ("bump thinking up to xhigh", "xhigh", 0),
    ("effort: low", "low", 0),
    ("go medium effort", "medium", 0),
    ("think harder about this proof", None, 1),
    ("think a bit less, this is easy", None, -1),
    ("don't overthink so much", None, -1),
    ("think as hard as you can", "max", 0),
    ("reset your effort", "default", 0),
])
def test_effort_switches(text, effort, step):
    s = _si().parse(text)
    assert (s.effort, s.step) == (effort, step)


@pytest.mark.parametrize("text", [
    "that was a low effort meme lol",
    "high effort shitpost incoming",
    "my thinking is that we should go",
    "I think less of him now",
])
def test_effort_non_switches(text):
    s = _si().parse(text)
    assert (s.effort, s.step) == (None, 0)


def test_rest_and_substantive():
    si = _si()
    only = si.parse("@MIST can you switch to sonnet please, thanks!")
    assert only.model == "sonnet" and not only.substantive
    both = si.parse("switch to sonnet and tell me a joke")
    assert both.model == "sonnet" and both.substantive
    assert "joke" in both.rest
    combo = si.parse("switch to opus, max effort")
    assert (combo.model, combo.effort, combo.substantive) == ("opus", "max", False)


def test_stepped_levels():
    si = _si()
    assert si.stepped("default", 1) == "max"
    assert si.stepped("default", -1) == "high"
    assert si.stepped("max", 1) == "max"
    assert si.stepped("low", -1) == "low"


def test_levels_match_models_module():
    assert _si().LEVELS == load_script("claude-bot/models.py").EFFORT_LEVELS
