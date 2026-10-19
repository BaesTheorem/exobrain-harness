"""claude-api-gate opens only at 100% of a plan window and fails closed."""

import importlib.machinery
import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "bin" / "claude-api-gate"
_loader = importlib.machinery.SourceFileLoader("claude_api_gate", str(_PATH))
_spec = importlib.util.spec_from_loader("claude_api_gate", _loader)
assert _spec is not None
gate = importlib.util.module_from_spec(_spec)
_loader.exec_module(gate)


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return json.dumps(self.body).encode()


def _setup(monkeypatch, body, token=True):
    creds = json.dumps({"claudeAiOauth": {"accessToken": "t"}}) if token else None
    monkeypatch.setattr(gate, "_keychain", lambda s: creds if s == gate.OAUTH_SERVICE else "sk-test")
    if isinstance(body, Exception):
        def boom(*a, **k):
            raise body
        monkeypatch.setattr(gate.urllib.request, "urlopen", boom)
    else:
        monkeypatch.setattr(gate.urllib.request, "urlopen", lambda *a, **k: _Resp(body))


@pytest.mark.parametrize("five,seven,expect", [
    (12, 54, False), (99.9, 99.9, False), (100, 10, True), (10, 100, True),
])
def test_threshold(monkeypatch, five, seven, expect):
    _setup(monkeypatch, {"five_hour": {"utilization": five}, "seven_day": {"utilization": seven}})
    assert gate.check()[0] is expect


@pytest.mark.parametrize("body", [
    gate.urllib.error.URLError("429"), {}, {"five_hour": {"utilization": 100}},
    {"five_hour": {"utilization": None}, "seven_day": {"utilization": 100}},
])
def test_fails_closed(monkeypatch, body):
    _setup(monkeypatch, body)
    assert gate.check()[0] is False


def test_no_token_closed(monkeypatch):
    _setup(monkeypatch, {"five_hour": {"utilization": 100}, "seven_day": {"utilization": 100}}, token=False)
    assert gate.check()[0] is False


def test_exec_closed_never_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "LOG", str(tmp_path / "log"))
    monkeypatch.setattr(gate, "check", lambda: (False, "x"))
    ran = []
    monkeypatch.setattr(gate.os, "execvpe", lambda *a: ran.append(a))
    assert gate.main(["exec", "--", "claude"]) == 3
    assert not ran


def test_exec_open_injects_key_only_in_child(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "LOG", str(tmp_path / "log"))
    monkeypatch.setattr(gate, "NOTIFY", str(tmp_path / "nope"))
    monkeypatch.setattr(gate, "check", lambda: (True, "x"))
    monkeypatch.setattr(gate, "_keychain", lambda s: "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ran = []
    monkeypatch.setattr(gate.os, "execvpe", lambda f, a, env: ran.append(env))
    gate.main(["exec", "--", "claude"])
    assert ran[0]["ANTHROPIC_API_KEY"] == "sk-test"
    assert "ANTHROPIC_API_KEY" not in gate.os.environ
    assert "sk-test" not in (tmp_path / "log").read_text()
