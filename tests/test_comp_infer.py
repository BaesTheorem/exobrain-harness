"""Tests for job-search/comp-infer.py (offline parts only)."""

from conftest import load_script

ci = load_script("job-search/comp-infer.py")


def test_similarity_ignores_level_words():
    assert ci.similarity("Senior IT Support Specialist II", "IT Support Specialist") == 1.0
    assert ci.similarity("Recovery Coach", "IT Support Specialist") == 0.0


def test_hourly_bands_annualize():
    assert ci.annual(30, 40, False) == (30 * 2080, 40 * 2080)
    assert ci.annual(60000, 80000, False) == (60000, 80000)


def test_detect_each_ats():
    assert ci.detect("https://jobs.lever.co/coalfire/abc")[1] == "coalfire"
    assert ci.detect("https://job-boards.greenhouse.io/expel/jobs/1")[1] == "expel"
    assert ci.detect("https://jobs.ashbyhq.com/equip/x")[1] == "equip"
    ats, board = ci.detect("https://rgare.wd1.myworkdayjobs.com/Careers/job/x")
    assert ats == "workday" and board["tenant"] == "rgare"
    assert ci.detect("https://example.com/careers") is None


def row(sim, lo, hi):
    return {"title": "t", "url": "u", "sim": sim, "lo": lo, "hi": hi}


def test_judge_ranges():
    floor = ci.comp_floor()
    assert ci.judge_ranges([], floor)[0] == 2
    assert ci.judge_ranges([row(0.95, 1, floor)], floor)[0] == 0            # same title alone
    assert ci.judge_ranges([row(0.5, 1, floor)], floor)[0] == 1             # one loose match
    assert ci.judge_ranges([row(0.5, 1, floor), row(0.4, 1, floor + 1)], floor)[0] == 0
    assert ci.judge_ranges([row(0.95, 1, floor - 1), row(0.5, 1, floor * 2)], floor)[0] == 1


def test_agent_needs_a_confirmed_figure(monkeypatch):
    monkeypatch.setattr(ci, "figure_on_page", lambda url, fig: False)
    res = {"found": True, "low": 1, "high": 10**7, "evidence": [{"url": "u", "figure": "$1"}]}
    assert ci.judge_agent(res, ci.comp_floor())[0] == 1
    monkeypatch.setattr(ci, "figure_on_page", lambda url, fig: True)
    assert ci.judge_agent(res, ci.comp_floor())[0] == 0
    assert ci.judge_agent({"found": False}, ci.comp_floor())[0] == 2
