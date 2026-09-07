"""Characterization tests for the fetch resilience in job-search/nicheboards.py.

Encodes the 2026-09-07 fix: a transient read timeout is retried, and a page
that still fails is a reported coverage gap, not the death of the Himalayas
lane (one stalled page among ten used to print DID NOT RUN over 199 good ones).
"""

import datetime as dt
import http.client
import json
import re
import urllib.error

import pytest
from conftest import load_script

nb = load_script("job-search/nicheboards.py")


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_get_retries_transient_failures(monkeypatch):
    calls = []

    def urlopen(req, timeout=30):
        calls.append(req.full_url)
        if len(calls) < 3:
            raise TimeoutError("timed out")
        return Resp(b'{"ok": true}')

    monkeypatch.setattr(nb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nb.time, "sleep", lambda s: None)
    assert nb._get("https://example.test/x") == '{"ok": true}'
    assert len(calls) == 3


def http_error(code, headers=None):
    msg = http.client.HTTPMessage()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://example.test/x", code, "nope", msg, None)


def test_get_waits_out_a_429_then_succeeds(monkeypatch):
    calls, sleeps = [], []

    def urlopen(req, timeout=30):
        calls.append(1)
        if len(calls) < 3:
            raise http_error(429)
        return Resp(b"[]")

    monkeypatch.setattr(nb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nb.time, "sleep", sleeps.append)
    assert nb._get("https://example.test/x") == "[]"
    assert sleeps == [nb.RATE_LIMIT_WAIT, nb.RATE_LIMIT_WAIT]


def test_get_honors_retry_after_on_429(monkeypatch):
    calls, sleeps = [], []

    def urlopen(req, timeout=30):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(429, {"Retry-After": "7"})
        return Resp(b"[]")

    monkeypatch.setattr(nb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nb.time, "sleep", sleeps.append)
    assert nb._get("https://example.test/x") == "[]"
    assert sleeps == [7.0]


def test_get_gives_up_after_attempts(monkeypatch):
    calls = []

    def urlopen(req, timeout=30):
        calls.append(1)
        raise TimeoutError("timed out")

    monkeypatch.setattr(nb.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nb.time, "sleep", lambda s: None)
    with pytest.raises(TimeoutError):
        nb._get("https://example.test/x")
    assert len(calls) == 3


def test_himalayas_page_failure_is_a_gap_not_a_lane_death(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)

    def get(url, timeout=30, attempts=3):
        m = re.search(r"offset=(\d+)", url)
        assert m is not None
        off = int(m.group(1))
        if off == 20:
            raise TimeoutError("stalled")
        if off >= 40:
            return json.dumps({"jobs": []})
        return json.dumps({"jobs": [
            {"title": "IT Analyst %d" % i, "pubDate": int(now.timestamp())}
            for i in range(20)]})

    monkeypatch.setattr(nb, "_get", get)
    rows, truncated, gaps = nb.himalayas(now - dt.timedelta(days=3))
    assert len(rows) == 20 and not truncated
    assert gaps == [(20, "TimeoutError: stalled")]


def test_himalayas_stops_at_the_cutoff(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    fresh, old = int(now.timestamp()), int((now - dt.timedelta(days=9)).timestamp())

    def get(url, timeout=30, attempts=3):
        return json.dumps({"jobs": [{"title": "x", "pubDate": fresh}] * 5
                           + [{"title": "y", "pubDate": old}] * 15})

    monkeypatch.setattr(nb, "_get", get)
    rows, truncated, gaps = nb.himalayas(now - dt.timedelta(days=3))
    assert len(rows) == 5 and not truncated and gaps == []
