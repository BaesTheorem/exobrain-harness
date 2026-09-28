"""Characterization tests for the gates in job-search/dice.py."""

from conftest import SYNTHETIC_ENV, load_script

dice = load_script("job-search/dice.py")


def band(lo, hi):
    return "USD %s.00 - %s.00 per year" % (f"{lo:,}", f"{hi:,}")


def card(**overrides):
    top = max(dice.COMP_FLOOR, dice.ONSITE_FLOOR)
    c = {"id": "x", "title": "Security Analyst", "company": "Acme", "where": "Remote • Today",
         "type": "Full-time", "salary": band(top, top + 20_000)}
    c.update(overrides)
    return c


def test_clean_remote_card_survives():
    assert dice.gate(card())[0] == "survivor"


def test_onsite_outside_kc_declines_on_gate1():
    verdict, why = dice.gate(card(where="Dallas, Texas • Today"))
    assert verdict == "decline" and why.startswith("gate1")


def test_floors_come_from_config():
    assert dice.COMP_FLOOR == int(SYNTHETIC_ENV["JOB_COMP_FLOOR"])
    assert dice.ONSITE_FLOOR == int(SYNTHETIC_ENV["JOB_ONSITE_FLOOR"])


def test_kc_onsite_uses_onsite_floor():
    # Band top equals the onsite floor, so it passes with flags.
    floor = dice.ONSITE_FLOOR
    verdict, why = dice.gate(card(where="Lenexa, Kansas • Today",
                                  salary=band(floor - 25_000, floor)))
    assert verdict == "survivor" and "KC-LOCAL" in why and "BAND-STRADDLE" in why
    assert f"{floor:,}" in why
    verdict, _ = dice.gate(card(where="Overland Park, Kansas",
                                salary=band(floor - 25_000, floor - 2_000)))
    assert verdict == "decline"


def test_contract_and_third_party_decline_on_gate2():
    for t in ("Full-time, Contract", "Full-time, Third Party"):
        verdict, why = dice.gate(card(type=t))
        assert verdict == "decline" and why.startswith("gate2")


def test_band_rule_and_hourly_annualization():
    floor = dice.COMP_FLOOR
    assert dice.gate(card(salary=band(floor - 15_000, floor - 1_000)))[0] == "decline"
    assert "BAND-STRADDLE" in dice.gate(card(salary=band(floor - 15_000, floor + 15_000)))[1]
    under = (floor - 2_080) / 2080  # hourly rate that annualizes to just under the floor
    assert dice.gate(card(salary="USD %.2f per hour" % under))[0] == "decline"
    over = (floor + 20_800) / 2080
    assert dice.gate(card(salary="USD %.2f - %.2f per hour" % (over, over + 5)))[0] == "survivor"


def test_unlisted_comp_is_a_lead():
    assert dice.gate(card(salary=""))[0] == "lead"
    assert dice.gate(card(salary="Depends on Experience"))[0] == "lead"


def test_title_filter():
    assert dice.gate(card(title="Senior Security Analyst"))[0] == "drop"
    assert dice.gate(card(title="Data Engineer"))[0] == "drop"
    assert dice.gate(card(title="Platform Associate Resident Consultant"))[0] == "survivor"
