"""limit-reset: parses the account's grants, picks the right one, claims at most once."""

import importlib.machinery
import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parent.parent / "bin" / "limit-reset"
_loader = importlib.machinery.SourceFileLoader("limit_reset", str(_PATH))
_spec = importlib.util.spec_from_loader("limit_reset", _loader)
assert _spec is not None
lr = importlib.util.module_from_spec(_spec)
_loader.exec_module(lr)

NOW = 1_800_000_000.0


def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def _grant(id="g1", kind="session", left=1, ends=NOW + 3 * 86400, clears=("five_hour",),
           usable=True, requires_limit=True, **extra):
    g = {"id": id, "label": f"{kind} reset", "resets_total": 2, "resets_left": left,
         "ends_at": _iso(ends), "clears": list(clears), "usable_now": usable,
         "use_requires_limit": requires_limit, "type": kind if kind in ("session", "weekly", "full") else None}
    g.update(extra)
    return g


def _status(grants=(), at_limit=False, exhausted=(), weekly_session=False):
    return lr.parse_status({
        "five_hour": {"utilization": 100 if "five_hour" in exhausted else 3, "resets_at": _iso(NOW + 3600)},
        "seven_day": {"utilization": 37, "resets_at": _iso(NOW + 86400)},
        "cedar_ember": {"eligible": bool(grants), "ineligible_reason": None if grants else "no_grant",
                        "at_limit": at_limit, "exhausted": list(exhausted), "grants": list(grants)},
        "juniper_tide": {"eligible": weekly_session, "available": weekly_session, "resets_per_week": 1},
    })


def test_live_shape_with_no_grant_parses_to_nothing():
    """The real response on 2026-10-26: eligible false, no_grant, empty grants."""
    s = _status()
    assert s["grants"] == [] and s["ineligible_reason"] == "no_grant"
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_missing_blocks_fail_safe():
    s = lr.parse_status({"five_hour": {}, "seven_day": {}})
    assert s["grants"] == [] and s["at_limit"] is False
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_kind_from_clears_when_type_missing():
    assert lr.grant_kind({"clears": ["five_hour"], "label": ""}) == "session"
    assert lr.grant_kind({"clears": ["seven_day"], "label": ""}) == "weekly"
    assert lr.grant_kind({"clears": ["five_hour", "seven_day"], "label": ""}) == "full"
    assert lr.grant_kind({"clears": ["seven_day"], "label": "Fable reset"}) == "fable"


def test_at_limit_picks_narrowest_grant_that_clears_the_window():
    s = _status(grants=[_grant("full", "full", clears=("five_hour", "seven_day")),
                        _grant("sess", "session")], at_limit=True, exhausted=["five_hour"])
    why, g = lr.decide(s, NOW, 6.0)
    assert (why, g["id"]) == ("at_limit", "sess")


def test_at_limit_skips_grant_that_does_not_clear_the_window():
    s = _status(grants=[_grant("sess", "session")], at_limit=True, exhausted=["seven_day"])
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_at_limit_falls_back_to_weekly_session_allowance():
    s = _status(at_limit=True, exhausted=["five_hour"], weekly_session=True)
    assert lr.decide(s, NOW, 6.0) == ("weekly_session", None)


@pytest.mark.parametrize("field,value", [("usable_now", False), ("paused", True),
                                         ("resets_left", 0), ("unavailable_reason", "cooldown")])
def test_unusable_grants_are_never_picked(field, value):
    s = _status(grants=[_grant(**{field: value})], at_limit=True, exhausted=["five_hour"])
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_expired_grant_is_never_picked():
    s = _status(grants=[_grant(ends=NOW - 60, requires_limit=False)], at_limit=True, exhausted=["five_hour"])
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_anytime_grant_is_used_only_inside_the_expiry_window():
    soon = _status(grants=[_grant("a", requires_limit=False, ends=NOW + 2 * 3600)])
    later = _status(grants=[_grant("b", requires_limit=False, ends=NOW + 2 * 86400)])
    assert lr.decide(soon, NOW, 6.0)[0] == "expiring"
    assert lr.decide(later, NOW, 6.0) == ("none", None)


def test_grant_that_needs_a_limit_is_not_used_early():
    s = _status(grants=[_grant(requires_limit=True, ends=NOW + 3600)])
    assert lr.decide(s, NOW, 6.0) == ("none", None)


def test_claim_posts_the_offered_grant_id_with_a_request_id(monkeypatch):
    sent = {}

    def fake_request(path, body=None, timeout=25):
        sent["path"], sent["body"] = path, body
        return {"result": "reset", "cleared": ["five_hour"], "resets_left": 1}
    monkeypatch.setattr(lr, "_request", fake_request)
    monkeypatch.setattr(lr, "_org_uuid", lambda: "org-1")
    res = lr.claim_grant("g1")
    assert sent["path"] == "/api/organizations/org-1/reset_rate_limits"
    assert sent["body"]["program"] == "cedar_ember" and sent["body"]["grant_id"] == "g1"
    assert len(sent["body"]["request_id"]) >= 32
    assert res["result"] == "reset" and res["cleared"] == ["five_hour"]


def test_claim_without_org_never_posts(monkeypatch):
    monkeypatch.setattr(lr, "_org_uuid", lambda: None)
    monkeypatch.setattr(lr, "_request", lambda *a, **k: pytest.fail("posted without an org"))
    assert lr.claim_grant("g1")["result"] == "auth_error"


def test_unknown_claim_result_reads_as_unavailable(monkeypatch):
    monkeypatch.setattr(lr, "_request", lambda *a, **k: {"result": "something_new"})
    monkeypatch.setattr(lr, "_org_uuid", lambda: "org-1")
    assert lr.claim_grant("g1")["result"] == "unavailable"


def test_watch_claims_once_and_notifies_once(monkeypatch, tmp_path):
    monkeypatch.setattr(lr, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(lr, "LOG", str(tmp_path / "log"))
    monkeypatch.setattr(lr, "read_status", lambda: _status(
        grants=[_grant("sess"), _grant("wk", "weekly", clears=("seven_day",))],
        at_limit=True, exhausted=["five_hour"]))
    claims, banners = [], []
    monkeypatch.setattr(lr, "claim_grant", lambda gid: claims.append(gid) or {"result": "reset", "cleared": ["five_hour"], "resets_left": 0})
    monkeypatch.setattr(lr, "_notify", lambda lines, ctx: banners.append(lines))
    import argparse
    assert lr.cmd_watch(argparse.Namespace(expiring_hours=6.0, quiet=True)) == 0
    assert claims == ["sess"]
    assert len(banners) == 1 and any("Used a 5-hour reset" in ln for ln in banners[0])
    assert sum("New limit reset" in ln for ln in banners[0]) == 2
    state = json.load(open(tmp_path / "state.json"))
    assert set(state["seen"]) == {"sess", "wk"}
    # A second run: nothing new, nothing claimed again when the server says not at limit.
    monkeypatch.setattr(lr, "read_status", lambda: _status(grants=[_grant("wk", "weekly", clears=("seven_day",))]))
    assert lr.cmd_watch(argparse.Namespace(expiring_hours=6.0, quiet=True)) == 0
    assert claims == ["sess"] and len(banners) == 1


def test_watch_warns_once_about_a_limit_only_grant_that_expires_soon(monkeypatch, tmp_path):
    monkeypatch.setattr(lr, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(lr, "LOG", str(tmp_path / "log"))
    monkeypatch.setattr(lr, "read_status", lambda: _status(grants=[_grant("g", ends=NOW + 10 * 3600)]))
    import datetime as dt

    class _Now(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(NOW, tz) if tz else cls.fromtimestamp(NOW)
    monkeypatch.setattr(lr.dt, "datetime", _Now)
    banners = []
    monkeypatch.setattr(lr, "_notify", lambda lines, ctx: banners.append(lines))
    import argparse
    lr.cmd_watch(argparse.Namespace(expiring_hours=6.0, quiet=True))
    lr.cmd_watch(argparse.Namespace(expiring_hours=6.0, quiet=True))
    warnings = [ln for b in banners for ln in b if "only works at a limit" in ln]
    assert len(warnings) == 1


def test_auth_error_exits_2_without_a_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(lr, "LOG", str(tmp_path / "log"))

    def boom():
        raise lr.AuthError("HTTP 401")
    monkeypatch.setattr(lr, "read_status", boom)
    monkeypatch.setattr(lr, "claim_grant", lambda gid: pytest.fail("claimed on a 401"))
    assert lr.main(["claim", "--auto", "--quiet"]) == 2
