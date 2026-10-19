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


def test_knockout_unmet_vetoes_even_at_high_score():
    rows = [("Bachelor's, no equivalent", "knockout", "Unmet")] + [(f"d{i}", "core", "Met") for i in range(9)]
    verdict, score, reasons = judge(note(*rows))
    assert verdict == "FAIL" and score == 0.9 and reasons[0].startswith("knockout")


def test_unmet_required_skill_is_scored_not_vetoed():
    rows = [("Familiarity with Jira", "required", "Unmet")] + [(f"d{i}", "core", "Met") for i in range(9)]
    assert judge(note(*rows))[:2] == ("PASS", 0.9)


def test_partials_count_half_and_threshold_is_065():
    rows = [(f"m{i}", "core", "Met") for i in range(3)] + [("p", "core", "Partial"), ("u", "core", "Unmet")]
    assert judge(note(*rows))[:2] == ("PASS", 0.7)
    rows = [(f"m{i}", "core", "Met") for i in range(3)] + [(f"u{i}", "core", "Unmet") for i in range(2)]
    assert judge(note(*rows))[:2] == ("FAIL", 0.6)


def test_restore_reverses_only_its_own_decline():
    txt = note(("Windows Server", "knockout", "Unmet"), *[(f"d{i}", "core", "Met") for i in range(5)])
    verdict, score, reasons = judge(txt)
    declined = fg.enforce("x", txt, score, reasons, fg.scorecard_rows(txt))
    back = fg.restore(declined)
    fm, _ = fg.frontmatter(back)
    assert fg.field(fm, "status") == "candidate" and fg.field(fm, "declined") == "false"
    assert "## Why skipped" not in back and "## Fit scorecard" in back
    manual = declined.replace("Gate 4 failed in `job-search/fit-gate.py`", "Comp under the floor.")
    assert fg.restore(manual) is None


def test_preferred_rows_do_not_score():
    rows = [(f"d{i}", "core", "Met") for i in range(5)] + [("nice", "preferred", "Unmet")] * 5
    assert judge(note(*rows))[:2] == ("PASS", 1.0)


def test_thin_table_is_incomplete_and_missing_table_is_unscored():
    assert judge(note(("d", "core", "Met")))[0] == "INCOMPLETE"
    assert judge("---\ntype: job-listing\n---\n# none\n")[0] == "UNSCORED"


def test_enforce_declines_and_keeps_raw_jd(tmp_path):
    txt = note(("Windows Server", "knockout", "Unmet"), *[(f"d{i}", "core", "Met") for i in range(5)])
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


def test_note_without_archived_jd_is_detected():
    assert fg.has_jd(note(("d", "core", "Met")) + "> " + "real posting text " * 80 + "\n")
    assert not fg.has_jd(note(("d", "core", "Met")))  # a one-line callout is a stub
    assert not fg.has_jd("---\ntype: job-listing\n---\n# X\n\n## Snapshot\n- Indeed row only\n")


def fm_of(**kv):
    return "\n".join(f"{k}: {v}" for k, v in kv.items())


def test_gate1_aggregator_label_is_not_evidence():
    assert fg.gate1(fm_of(remote="true"))[0] == "NOLOC"
    assert fg.gate1(fm_of(remote="true", location_evidence="label"))[0] == "NOLOC"


def test_gate1_verified_remote_local_and_fellowship_pass():
    for ev in ("remote-jd", "remote-ats", "kc-local", "warm-exception"):
        assert fg.gate1(fm_of(location_evidence=ev)) is None
    assert fg.gate1(fm_of(role_type="fellowship")) is None


def test_gate1_relocation_fails_and_lane_decline_conflicts():
    assert fg.gate1(fm_of(location_evidence="relocation"))[0] == "RELOC"
    assert fg.gate1(fm_of(location_evidence="remote-jd", lane_decline='"x"'))[0] == "CONFLICT"


def test_gate1_decline_is_restorable():
    txt = note(*[(f"d{i}", "core", "Met") for i in range(5)])
    declined = fg.enforce("x", txt, 1.0, ["gate 1: on-site outside KC"], fg.scorecard_rows(txt))
    assert "Gate 1 failed" in declined
    assert "## Why skipped" not in fg.restore(declined)


def test_gate3_unlisted_comp_needs_a_recorded_inference():
    assert fg.gate3(fm_of(comp_listed="false"))[0] == "NOCOMP"
    assert fg.gate3(fm_of(comp_listed="true", comp_max=""))[0] == "NOCOMP"
    assert fg.gate3(fm_of(comp_listed="false", comp_inference='"same-employer band $90-110K"')) is None
    assert fg.gate3(fm_of(comp_listed="true", comp_max="90000")) is None


def test_gate0_intermediary_repost_needs_the_original_listing():
    fm = 'company: "Jobgether (client, unnamed)"\nsource: "lever"\napply_url: "https://jobs.lever.co/jobgether/x"'
    assert fg.gate0(fm)[0] == "REPOST"
    assert fg.gate0(fm + '\noriginal_listing: "https://job-boards.greenhouse.io/acme/jobs/1"') is None
    assert fg.gate0(fm + '\noriginal_unfound: "ATS X-ray on two JD phrases, Remotive, LinkedIn"') is None
    assert fg.gate0('company: "Acme"\nsource: "greenhouse"\napply_url: "https://job-boards.greenhouse.io/acme/jobs/1"') is None
