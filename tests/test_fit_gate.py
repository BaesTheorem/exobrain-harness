"""Tests for the gate-4 decision rule in job-search/fit-gate.py."""

from conftest import load_script

fg = load_script("job-search/fit-gate.py")

HEAD = """---
type: "job-listing"
status: candidate
applied: false
---
# X

## Fit scorecard
| # | JD line | Kind | Asks | Alex | Verdict | Evidence |
|---|---|---|---|---|---|---|
"""


def note(*rows):
    lines = [f'| {i} | "{line}" | {kind} | A | A | {verdict} | e |'
             for i, (line, kind, verdict) in enumerate(rows, 1)]
    return HEAD + "\n".join(lines) + "\n\n> [!info]- Raw JD\n> text | with | pipes\n"


def judge(txt):
    return fg.judge(fg.scorecard_rows(txt))


def test_all_met_passes():
    assert judge(note(*[(f"d{i}", "core", "Met") for i in range(5)]))[0] == "PASS"


def test_required_unmet_is_a_knockout_even_at_high_score():
    rows = [("Windows Server", "required", "Unmet")] + [(f"d{i}", "core", "Met") for i in range(9)]
    verdict, score, reasons = judge(note(*rows))
    assert verdict == "FAIL" and score == 0.9 and reasons[0].startswith("knockout")


def test_partials_count_half_and_threshold_is_080():
    rows = [(f"m{i}", "core", "Met") for i in range(3)] + [(f"p{i}", "core", "Partial") for i in range(2)]
    assert judge(note(*rows))[:2] == ("PASS", 0.8)
    rows = [(f"m{i}", "core", "Met") for i in range(3)] + [(f"p{i}", "core", "Partial") for i in range(3)]
    assert judge(note(*rows))[0] == "FAIL"


def test_preferred_rows_do_not_score():
    rows = [(f"d{i}", "core", "Met") for i in range(5)] + [("nice", "preferred", "Unmet")] * 5
    assert judge(note(*rows))[:2] == ("PASS", 1.0)


def test_thin_table_is_incomplete_and_missing_table_is_unscored():
    assert judge(note(("d", "core", "Met")))[0] == "INCOMPLETE"
    assert judge("---\ntype: job-listing\n---\n# none\n")[0] == "UNSCORED"


def test_enforce_declines_and_keeps_raw_jd(tmp_path):
    txt = note(("Windows Server", "required", "Unmet"), *[(f"d{i}", "core", "Met") for i in range(5)])
    verdict, score, reasons = judge(txt)
    out = fg.enforce("x", txt, score, reasons, fg.scorecard_rows(txt))
    fm, _ = fg.frontmatter(out)
    assert fg.field(fm, "status") == "skipped" and fg.field(fm, "declined") == "true"
    assert out.index("## Why skipped") < out.index("## Fit scorecard")
    assert "> text | with | pipes" in out


def test_met_below_asked_level_is_invalid():
    txt = HEAD + '| 1 | "Deploy AVD" | core | Own/Build | Support | Met | e |\n' + "\n".join(
        f'| {i} | "d{i}" | core | Administer | Administer | Met | e |' for i in range(2, 7)) + "\n"
    verdict, _, reasons = judge(txt)
    assert verdict == "INVALID" and "below" in reasons[0]


def test_pipe_inside_a_quote_is_reported_not_dropped():
    txt = note(*[(f"d{i}", "core", "Met") for i in range(5)]).replace(
        '| 1 | "d0" | core | A | A | Met | e |', '| 1 | "a | b" | core | Met |')
    assert judge(txt)[0] == "INVALID"


def test_knockout_kind_vetoes_and_preferred_does_not():
    rows = [("Bachelor's, no equivalent", "knockout", "Unmet")] + [(f"d{i}", "core", "Met") for i in range(9)]
    assert judge(note(*rows))[0] == "FAIL"
