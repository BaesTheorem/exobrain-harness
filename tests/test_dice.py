"""Characterization tests for the gates in job-search/dice.py."""

from conftest import load_script

dice = load_script("job-search/dice.py")


def card(**overrides):
    c = {"id": "x", "title": "Security Analyst", "company": "Acme", "where": "Remote • Today",
         "type": "Full-time", "salary": "USD 80,000.00 - 100,000.00 per year"}
    c.update(overrides)
    return c


def test_clean_remote_card_survives():
    assert dice.gate(card())[0] == "survivor"


def test_onsite_outside_kc_declines_on_gate1():
    verdict, why = dice.gate(card(where="Dallas, Texas • Today"))
    assert verdict == "decline" and why.startswith("gate1")


def test_kc_onsite_uses_onsite_floor():
    # $55K-$80K: band top equals the $80K onsite floor, so it passes with flags.
    verdict, why = dice.gate(card(where="Lenexa, Kansas • Today",
                                  salary="USD 55,000.00 - 80,000.00 per year"))
    assert verdict == "survivor" and "KC-LOCAL" in why and "BAND-STRADDLE" in why
    verdict, _ = dice.gate(card(where="Overland Park, Kansas",
                                salary="USD 55,000.00 - 78,000.00 per year"))
    assert verdict == "decline"


def test_contract_and_third_party_decline_on_gate2():
    for t in ("Full-time, Contract", "Full-time, Third Party"):
        verdict, why = dice.gate(card(type=t))
        assert verdict == "decline" and why.startswith("gate2")


def test_band_rule_and_hourly_annualization():
    assert dice.gate(card(salary="USD 60,000.00 - 74,000.00 per year"))[0] == "decline"
    assert "BAND-STRADDLE" in dice.gate(card(salary="USD 60,000.00 - 90,000.00 per year"))[1]
    assert dice.gate(card(salary="USD 22.50 per hour"))[0] == "decline"  # $46,800/yr
    assert dice.gate(card(salary="USD 40.00 - 48.00 per hour"))[0] == "survivor"


def test_unlisted_comp_is_a_lead():
    assert dice.gate(card(salary=""))[0] == "lead"
    assert dice.gate(card(salary="Depends on Experience"))[0] == "lead"


def test_title_filter():
    assert dice.gate(card(title="Senior Security Analyst"))[0] == "drop"
    assert dice.gate(card(title="Data Engineer"))[0] == "drop"
    assert dice.gate(card(title="Platform Associate Resident Consultant"))[0] == "survivor"
