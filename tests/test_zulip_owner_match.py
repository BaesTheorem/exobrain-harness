"""Tests for zulip/owner_match.py: which minted bots may be handed to whom."""

from conftest import load_script

om = load_script("zulip/owner_match.py")

ADMIN = 1


def _m(uid, name, bot=False, owner=None, active=True):
    d = {"user_id": uid, "full_name": name, "is_bot": bot, "is_active": active}
    if bot:
        d["bot_owner_id"] = owner
    return d


def test_transfer_when_exactly_one_human_matches():
    members = [_m(1, "Alex"), _m(2, "Heidi Bickner"), _m(10, "Heidi's Claude", bot=True, owner=1),
               _m(11, "MIST", bot=True, owner=1)]
    transfers, pending, ambiguous = om.plan_transfers(members, ADMIN)
    assert [(b["user_id"], h["user_id"]) for b, h in transfers] == [(10, 2)]
    assert pending == [] and ambiguous == []


def test_pending_until_the_person_joins():
    members = [_m(1, "Alex"), _m(10, "Heidi's Claude", bot=True, owner=1)]
    transfers, pending, ambiguous = om.plan_transfers(members, ADMIN)
    assert transfers == [] and [b["user_id"] for b in pending] == [10]


def test_two_humans_with_the_same_first_name_is_ambiguous():
    members = [_m(1, "Alex"), _m(2, "Sam A"), _m(3, "Sam B"), _m(10, "Sam's Claude", bot=True, owner=1)]
    transfers, pending, ambiguous = om.plan_transfers(members, ADMIN)
    assert transfers == [] and pending == [] and ambiguous[0][0]["user_id"] == 10


def test_bots_already_owned_by_someone_else_or_deactivated_are_ignored():
    members = [_m(1, "Alex"), _m(2, "Heidi"), _m(10, "Heidi's Claude", bot=True, owner=2),
               _m(12, "Test's Claude", bot=True, owner=1, active=False), _m(3, "Test")]
    transfers, pending, ambiguous = om.plan_transfers(members, ADMIN)
    assert transfers == [] and pending == [] and ambiguous == []


def test_admin_is_never_a_match_and_name_matching_ignores_case():
    members = [_m(1, "Alex"), _m(2, "heidi"), _m(10, "Heidi's Claude", bot=True, owner=1),
               _m(11, "Alex's Claude", bot=True, owner=1)]
    transfers, pending, ambiguous = om.plan_transfers(members, ADMIN)
    assert [(b["user_id"], h["user_id"]) for b, h in transfers] == [(10, 2)]
    assert [b["user_id"] for b in pending] == [11]
