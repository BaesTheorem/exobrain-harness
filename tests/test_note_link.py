"""Tests for job-search/note_link.py: lane declines written back onto notes."""

import datetime as dt

from conftest import load_script

nl = load_script("job-search/note_link.py")

NOTE = """---
type: job-listing
role: "Enterprise Access Management Analyst"
status: candidate
applied: false
---
# X
Retry rgare.wd1.myworkdayjobs.com/en-US/Careers

## Fit scorecard
| # | a |
"""


def test_match_record_and_idempotence(tmp_path):
    p = tmp_path / "RGA - EAM.md"
    p.write_text(NOTE)
    notes = nl.active_notes(str(tmp_path))
    hits = nl.match(notes, "rgare.wd1.myworkdayjobs.com", "Enterprise Access Management Analyst", "J1")
    assert hits == [str(p)]
    assert nl.match(notes, "other.wd1.myworkdayjobs.com", "Enterprise Access Management Analyst", "J1") == []
    assert nl.record(str(p), "workday.py", "J1", "EAM", "gate 1: St. Louis", "u", dt.date(2026, 10, 11))
    txt = p.read_text()
    assert 'lane_decline: "2026-10-11 workday.py: gate 1: St. Louis"' in txt
    assert txt.index("## Lane decline") < txt.index("## Fit scorecard")
    assert not nl.record(str(p), "workday.py", "J1", "EAM", "gate 1", "u")
