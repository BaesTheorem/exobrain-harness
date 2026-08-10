"""Characterization tests for the four hard gates in job-search/hiringcafe.py.

These encode the job-filter rules (remote-only, full-time, comp floor with
unlisted-comp DQ, no hard degree/clearance bars). If a gate's behavior
changes, that should be a deliberate /job-search decision, not a side effect.
"""

from conftest import load_script

hc = load_script("job-search/hiringcafe.py")


def make_hit(**overrides):
    v = {
        "workplace_type": "Remote",
        "workplace_countries": ["US"],
        "commitment": ["Full Time"],
        "is_compensation_transparent": True,
        "yearly_max_compensation": 95_000,
        "bachelors_degree_requirement": "Preferred",
        "min_industry_and_role_yoe": 4,
        "security_clearance": None,
        "estimated_publish_date_millis": None,
    }
    v.update(overrides)
    return {"v5_processed_job_data": v}


def test_clean_hit_passes():
    passed, reason = hc.gate(make_hit(), max_age_days=7)
    assert passed, reason


def test_gate1_onsite_dq():
    passed, reason = hc.gate(make_hit(workplace_type="Hybrid"), 7)
    assert not passed and "gate1" in reason


def test_gate1_non_us_dq():
    passed, reason = hc.gate(make_hit(workplace_countries=["DE"]), 7)
    assert not passed and "gate1" in reason


def test_gate2_part_time_dq():
    passed, reason = hc.gate(make_hit(commitment=["Part Time"]), 7)
    assert not passed and "gate2" in reason


def test_gate3_unlisted_comp_is_dq_by_default():
    passed, reason = hc.gate(make_hit(is_compensation_transparent=False), 7)
    assert not passed and "gate3" in reason
    passed, reason = hc.gate(make_hit(yearly_max_compensation=None), 7)
    assert not passed and "gate3" in reason


def test_gate3_comp_floor_boundary():
    # Floor is $75K; a band topping out exactly at the floor passes.
    passed, _ = hc.gate(make_hit(yearly_max_compensation=hc.COMP_FLOOR), 7)
    assert passed
    passed, reason = hc.gate(make_hit(yearly_max_compensation=hc.COMP_FLOOR - 1), 7)
    assert not passed and "gate3" in reason


def test_gate4_hard_degree_requirement_dq():
    passed, reason = hc.gate(make_hit(bachelors_degree_requirement="Required"), 7)
    assert not passed and "gate4" in reason


def test_gate4_clearance_dq():
    passed, reason = hc.gate(make_hit(security_clearance="Secret"), 7)
    assert not passed and "gate4" in reason


def test_gate4_yoe_over_8_dq():
    passed, reason = hc.gate(make_hit(min_industry_and_role_yoe=10), 7)
    assert not passed and "gate4" in reason


def test_missing_processed_data_never_crashes():
    passed, _ = hc.gate({}, 7)
    assert not passed
    passed, _ = hc.gate({"v5_processed_job_data": None}, 7)
    assert not passed
