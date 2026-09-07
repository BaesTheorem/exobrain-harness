"""Characterization tests for the crawl bounds in job-search/workday.py.

These encode the 2026-09-07 fixes: `total` comes from page one only (wd5
tenants report 0 on later pages, which silently truncated every unfiltered
board to 40 postings), a whole-tenant crawl is bounded by a page cap and a
wall-clock deadline and says so, an incremental poll stops once it catches up
with the snapshot, and the snapshot is a merge rather than an overwrite.
"""

import datetime as dt

from conftest import load_script

wd = load_script("job-search/workday.py")


def board(**over):
    b = {"host": "x.wd5.myworkdayjobs.com", "tenant": "x", "site": "S",
         "facets": {}, "search": ""}
    b.update(over)
    return b


def fake_tenant(pages, total_first, total_later=0):
    """A `_req` stand-in serving `pages` (lists of req ids) 20 at a time."""
    def _req(url, body=None, timeout=20):
        assert body is not None and url.endswith("/jobs")
        offset = body["offset"]
        ids = pages[offset // wd.PAGE] if offset // wd.PAGE < len(pages) else []
        return {
            "total": total_first if offset == 0 else total_later,
            "jobPostings": [
                {"title": "Security Analyst %s" % r, "bulletFields": [r],
                 "externalPath": "/job/%s" % r, "locationsText": "Remote",
                 "postedOn": "Posted Today"} for r in ids],
        }
    return _req


def ids(prefix, n):
    return ["%s%03d" % (prefix, i) for i in range(n)]


def chunk(seq, size=20):
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def test_total_is_read_from_the_first_page_only(monkeypatch):
    # 579 postings; the tenant says total=579 on page one and 0 afterwards.
    # The old loop re-read total each page and stopped at 40.
    monkeypatch.setattr(wd, "_req", fake_tenant(chunk(ids("R", 579)), 579, 0))
    jobs, meta = wd.poll(board())
    assert len(jobs) == 579
    assert meta["pages"] == 29
    assert meta["total"] == 579
    assert meta["stopped"] == "end of board"


def test_page_cap_truncates_loudly(monkeypatch):
    monkeypatch.setattr(wd, "MAX_PAGES", 5)
    monkeypatch.setattr(wd, "_req", fake_tenant(chunk(ids("R", 2000)), 19016, 19016))
    jobs, meta = wd.poll(board())
    assert len(jobs) == 100
    assert meta["pages"] == 5
    assert "TRUNCATED" in meta["stopped"] and "5-page cap" in meta["stopped"]


def test_incremental_poll_stops_once_caught_up(monkeypatch):
    known = ids("K", 200)
    pages = chunk(["N1", "N2"] + known[:18]) + chunk(known[18:])
    monkeypatch.setattr(wd, "_req", fake_tenant(pages, 202, 0))

    jobs, meta = wd.poll(board(), set(known))
    # page 0 holds the two new reqs; pages 1 and 2 are entirely known -> stop.
    assert meta["pages"] == 3
    assert {"N1", "N2"} <= set(jobs)
    assert "caught up" in meta["stopped"]

    # A baseline (nothing known) has nothing to catch up with: full crawl.
    jobs, meta = wd.poll(board(), set())
    assert meta["pages"] == len(pages) and meta["stopped"] == "end of board"

    # Faceted boards come back in mixed order, so they never early-stop.
    jobs, meta = wd.poll(board(facets={"loc": ["guid"]}), set(known))
    assert meta["pages"] == len(pages) and meta["stopped"] == "end of board"


def test_deadline_is_a_loud_stop(monkeypatch):
    monkeypatch.setattr(wd, "BOARD_DEADLINE", -1)
    monkeypatch.setattr(wd, "_req", fake_tenant(chunk(ids("R", 60)), 60, 0))
    jobs, meta = wd.poll(board())
    assert jobs == {} and meta["pages"] == 0
    assert "deadline" in meta["stopped"]


def test_merge_snapshot_keeps_history_and_ages_out():
    today = dt.date.today()
    stamp = lambda days: (today - dt.timedelta(days=days)).isoformat()  # noqa: E731
    prev = {
        "a/A": {"old": {"title": "t", "last_seen": stamp(100)},
                "recent": {"title": "t", "last_seen": stamp(10)},
                "legacy": {"title": "t"}},  # pre-v2 entry, no stamp
        "b/B": {"kept": {"title": "t"}},  # this board failed this run
        "__meta__": {"written": "yesterday"},
    }
    snap = {"a/A": {"new": {"title": "n"}}}
    merged = wd.merge_snapshot(prev, snap)
    assert set(merged["a/A"]) == {"recent", "legacy", "new"}
    assert merged["a/A"]["new"]["last_seen"] == today.isoformat()
    assert merged["b/B"] == {"kept": {"title": "t"}}
    assert "v2" in merged["__meta__"]["crawl"]


def detail(**over):
    d = {"title": "", "loc": "", "time_type": "Full time", "can_apply": True,
         "posted": True, "lo": 90_000.0, "hi": 120_000.0}
    d.update(over)
    return d


def test_gate_declines_non_us_remote_seats():
    row = {"title": "Analyst I, Falcon Complete (Remote, PST/MST)", "loc": "Canada - Remote AB"}
    verdict, why = wd.gate(row, detail())
    assert verdict == "decline" and "non-US" in why
    row = {"title": "Insider Risk Analyst (Remote, GBR)", "loc": "United Kingdom - Remote"}
    assert wd.gate(row, detail())[0] == "decline"
    # the code in the title alone is enough
    row = {"title": "Technical Support Engineer (Remote, BRA)", "loc": "Remote"}
    assert wd.gate(row, detail())[0] == "decline"


def test_gate_accepts_us_remote_spellings():
    for loc in ["US - Remote", "USA - Remote, TX", "United States Work at Home",
                "Remote - Oregon"]:
        verdict, why = wd.gate({"title": "Security Analyst", "loc": loc}, detail())
        assert verdict == "pass", (loc, why)


def test_gate_hybrid_marker_in_title_beats_remote_location():
    row = {"title": "Analyst I, Falcon Complete GovCloud (Hybrid, St Louis)", "loc": "USA - Remote"}
    verdict, why = wd.gate(row, detail())
    assert verdict == "decline" and "hybrid" in why


def test_gate_order_ats_closed_then_type_then_location_then_comp():
    row = {"title": "Security Analyst", "loc": "US - Remote"}
    assert wd.gate(row, detail(can_apply=False))[0] == "decline"
    assert wd.gate(row, detail(time_type="Part time"))[1].startswith("gate 2")
    assert wd.gate(row, detail(loc="Plano, TX"))[1].startswith("gate 1")
    assert wd.gate(row, detail(lo=None, hi=None))[0] == "lead"
    assert wd.gate(row, detail(lo=50_000.0, hi=70_000.0))[1].startswith("gate 3")
    verdict, why = wd.gate(row, detail(lo=60_000.0, hi=90_000.0))
    assert verdict == "pass" and "BAND-STRADDLE" in why


def test_title_prefilter_drops_sales_and_keeps_analysts():
    assert not wd.in_lane("Sales Specialist, Cloud Security (Remote, GBR)")
    assert wd.in_lane("Analyst I, Falcon Complete (Remote)")
    assert not wd.in_lane("Senior Security Analyst")


def test_recent_label_regex():
    for s in ["Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 7 Days Ago"]:
        assert wd.RECENT.search(s), s
    for s in ["Posted 8 Days Ago", "Posted 14 Days Ago", "Posted 30+ Days Ago", ""]:
        assert not wd.RECENT.search(s), s
