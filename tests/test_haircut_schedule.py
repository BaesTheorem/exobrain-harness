"""Tests for the haircut cadence gate (salon-ramon/schedule.py).

The tracker outlived the venue: it moved from the Booksy tool to the Rosy one
unchanged, because none of the cadence logic depends on which shop is booking.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SALON = Path(__file__).resolve().parent.parent / "salon-ramon"


def load_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: dict | None):
    """Import schedule.py with its state/config redirected at a temp dir."""
    spec = importlib.util.spec_from_file_location("haircut_schedule", SALON / "schedule.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations via sys.modules, so register before exec.
    sys.modules["haircut_schedule"] = mod
    spec.loader.exec_module(mod)

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"intervalWeeks": 6}))
    state_file = tmp_path / "state.json"
    if state is not None:
        state_file.write_text(json.dumps(state))

    monkeypatch.setattr(mod, "CONFIG_PATH", config)
    monkeypatch.setattr(mod, "STATE_PATH", state_file)
    return mod


def test_no_history_acts_immediately(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, None)
    st = mod.status(date(2031, 8, 17))
    assert st.should_act
    assert st.last_haircut is None


def test_not_due_stays_quiet(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-08-16"})
    st = mod.status(date(2031, 8, 17))
    assert not st.should_act
    assert st.due == date(2031, 9, 27)
    assert st.days_until_due == 41


def test_acts_inside_lead_window(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-08-16"})
    # Due 2031-09-27; LEAD_DAYS is 12, so 09-16 is inside the window.
    st = mod.status(date(2031, 9, 16))
    assert st.should_act
    assert st.days_until_due == 11


def test_nudges_only_once_per_cycle(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2031-08-16", "notified_cycle": "2031-09-27"},
    )
    st = mod.status(date(2031, 9, 16))
    assert not st.should_act
    assert "already nudged" in st.reason


def test_due_derives_from_haircut_not_notification(tmp_path, monkeypatch):
    """An ignored nudge must not slide the schedule later."""
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2031-08-16", "notified_cycle": "2031-09-27"},
    )
    # Well past the due date and still ignored: due stays put, and because the
    # cycle is unchanged we do not re-nudge -- but the date has not drifted.
    st = mod.status(date(2031, 10, 21))
    assert st.due == date(2031, 9, 27)
    assert st.days_until_due == -24


def test_record_resets_the_cycle(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2031-08-16", "notified_cycle": "2031-09-27"},
    )
    mod.main(["record", "--date", "2031-09-27", "--provider", "[Stylist]"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_haircut"] == "2031-09-27"
    assert state["notified_cycle"] is None
    assert state["history"][-1]["provider"] == "[Stylist]"


def test_pending_appointment_silences_the_daily_job(tmp_path, monkeypatch):
    """The bootstrap case: no history, but a cut is already booked."""
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": None, "pending": "2031-08-30"})
    assert not mod.status(date(2031, 8, 18)).should_act
    assert not mod.status(date(2031, 8, 30)).should_act  # the day itself


def test_job_wakes_again_after_the_appointment_passes(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": None, "pending": "2031-08-30"})
    st = mod.status(date(2031, 8, 31))
    assert st.should_act
    assert st.reason == "no haircut on record yet"


def test_pending_does_not_suppress_a_later_due_cycle(tmp_path, monkeypatch):
    """A spent appointment must not silence the next cycle forever."""
    mod = load_schedule(
        tmp_path, monkeypatch, {"last_haircut": "2031-08-30", "pending": "2031-08-30"}
    )
    # Next due 2031-10-11; inside the lead window and the appointment is past.
    st = mod.status(date(2031, 10, 2))
    assert st.should_act
    assert st.due == date(2031, 10, 11)


def test_record_clears_the_pending_appointment(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": None, "pending": [{"date": "2031-08-30", "provider": "[Stylist]"}]},
    )
    mod.main(["record", "--date", "2031-08-30", "--provider", "[Stylist]"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["pending"] == []
    assert state["pending"] == []
    assert state["last_haircut"] == "2031-08-30"


def test_search_window_never_starts_in_the_past(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-06-02"})
    today = date(2031, 8, 17)
    start, end = mod.search_window(today)
    assert start > today
    assert end > start
    assert (end - start) <= timedelta(days=90)


# --- reconcile: a lapsed appointment must not vanish --------------------


def test_lapsed_appointment_records_as_completed(tmp_path, monkeypatch):
    """The missed-close-out bug: the cut happened, the pending expired, history stayed empty.

    The next run then read "no haircut on record", which is the one state that
    makes the job act immediately, and it went hunting three weeks early.
    """
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": None, "pending": [{"date": "2031-09-02", "provider": "[Stylist]"}], "history": []},
    )
    assert mod.reconcile(date(2031, 9, 9)) == date(2031, 9, 2)

    st = mod.status(date(2031, 9, 9))
    assert st.last_haircut == date(2031, 9, 2)
    assert st.due == date(2031, 10, 14)
    assert not st.should_act, "a recorded cut must stop the early hunt"

    entry = json.loads((tmp_path / "state.json").read_text())["history"][-1]
    assert entry == {"date": "2031-09-02", "assumed": True, "provider": "[Stylist]"}


def test_reconcile_leaves_a_future_appointment_alone(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path, monkeypatch, {"last_haircut": None, "pending": "2031-09-21", "history": []}
    )
    assert mod.reconcile(date(2031, 9, 9)) is None
    assert json.loads((tmp_path / "state.json").read_text())["pending"] == "2031-09-21"


def test_reconcile_does_not_double_record_a_hand_logged_cut(tmp_path, monkeypatch):
    """Alex recording it himself must retire the appointment, not duplicate it."""
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {
            "last_haircut": "2031-09-02",
            "pending": "2031-09-02",
            "history": [{"date": "2031-09-02"}],
        },
    )
    assert mod.reconcile(date(2031, 9, 9)) is None
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["pending"] == []
    assert len(state["history"]) == 1


def test_reconcile_is_a_noop_without_an_appointment(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-09-02", "history": []})
    assert mod.reconcile(date(2031, 9, 9)) is None


def test_a_scalar_pending_migrates_to_the_queue(tmp_path, monkeypatch):
    """State written by the single-appointment version still loads."""
    mod = load_schedule(
        tmp_path, monkeypatch,
        {"last_haircut": "2031-09-02", "pending": "2031-10-14", "pending_provider": "[Stylist]"},
    )
    state = mod.load_state()
    assert state["pending"] == [{"date": "2031-10-14", "provider": "[Stylist]"}]
    assert "pending_provider" not in state
    assert mod.status(date(2031, 9, 12)).pending == date(2031, 10, 14)


def test_two_booked_cycles_both_suppress_the_job(tmp_path, monkeypatch):
    """The bug this queue exists to prevent.

    Book two cycles ahead, let the first one pass, and the job must still stay
    quiet. With a single `pending` slot the second booking overwrote the first,
    so the morning after the October cut the job saw an empty diary and booked
    a second November haircut on top of the one already on the books.
    """
    mod = load_schedule(
        tmp_path, monkeypatch,
        {
            "last_haircut": "2031-09-02",
            "pending": [
                {"date": "2031-10-14", "provider": "[Stylist]"},
                {"date": "2031-11-26", "provider": "[Stylist]"},
            ],
            "history": [],
        },
    )
    # Before the first appointment: quiet, pointing at October.
    assert mod.status(date(2031, 10, 2)).should_act is False
    assert mod.status(date(2031, 10, 2)).pending == date(2031, 10, 14)

    # The October cut happens and gets closed out.
    assert mod.reconcile(date(2031, 10, 15)) == date(2031, 10, 14)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_haircut"] == "2031-10-14"
    assert state["pending"] == [{"date": "2031-11-26", "provider": "[Stylist]"}]

    # The morning after: due 2031-11-25, inside the 12-day lead, and yet quiet,
    # because November is already booked.
    st = mod.status(date(2031, 11, 21))
    assert st.due == date(2031, 11, 25)
    assert st.should_act is False
    assert st.pending == date(2031, 11, 26)


def test_reconcile_closes_out_several_missed_appointments_at_once(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path, monkeypatch,
        {
            "last_haircut": "2031-09-02",
            "pending": [{"date": "2031-10-14"}, {"date": "2031-11-26"}],
            "history": [],
        },
    )
    assert mod.reconcile(date(2031, 12, 2)) == date(2031, 11, 26)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_haircut"] == "2031-11-26"
    assert state["pending"] == []
    assert [h["date"] for h in state["history"]] == ["2031-10-14", "2031-11-26"]
    assert all(h["assumed"] for h in state["history"])


def test_recording_one_cut_keeps_a_later_booking(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path, monkeypatch,
        {
            "last_haircut": "2031-09-02",
            "pending": [{"date": "2031-10-14"}, {"date": "2031-11-26"}],
            "history": [],
        },
    )
    mod.main(["record", "--date", "2031-10-14", "--provider", "[Stylist]"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["pending"] == [{"date": "2031-11-26"}]


def test_pending_appends_rather_than_replacing(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-09-02"})
    mod.main(["pending", "--date", "2031-11-26", "--provider", "[Stylist]"])
    mod.main(["pending", "--date", "2031-10-14", "--provider", "[Stylist]"])
    mod.main(["pending", "--date", "2031-10-14", "--provider", "[Stylist]"])  # idempotent
    state = json.loads((tmp_path / "state.json").read_text())
    assert [e["date"] for e in state["pending"]] == ["2031-10-14", "2031-11-26"]


def _ahead(mod, tmp_path, n=2):
    (tmp_path / "config.json").write_text(json.dumps({
        "intervalWeeks": 6, "bookAhead": n,
        "preferWeekdays": True, "preferredWindow": ["10:00", "18:00"],
    }))


def test_book_ahead_quiet_with_two_queued(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {
        "last_haircut": "2031-08-16",
        "pending": [{"date": "2031-09-27"}, {"date": "2031-11-08"}],
    })
    _ahead(mod, tmp_path)
    assert not mod.status(date(2031, 8, 17)).should_act


def test_book_ahead_hunts_past_the_last_queued(tmp_path, monkeypatch):
    # One queued, bookAhead 2: hunt NOW for the cut 6 weeks after the queued one,
    # not 12 days before a due date anchored on the completed cut.
    mod = load_schedule(tmp_path, monkeypatch, {
        "last_haircut": "2031-08-16", "pending": [{"date": "2031-09-27"}],
    })
    _ahead(mod, tmp_path)
    st = mod.status(date(2031, 8, 17))
    assert st.should_act
    assert st.due == date(2031, 11, 8)
    hunt = mod.plan(date(2031, 8, 17))["hunt"]
    assert hunt["since"] == "2031-11-03" and hunt["until"] == "2031-11-17"


def test_book_ahead_one_keeps_the_original_gate(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2031-08-16"})
    _ahead(mod, tmp_path, n=1)
    assert not mod.status(date(2031, 8, 17)).should_act


def test_swap_candidates_keep_only_preferred_unrejected(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"rejected": ["2032-01-06 14:00"]})
    _ahead(mod, tmp_path)
    slots = [{"start": s} for s in (
        "2032-01-05T08:00:00",  # Monday, too early
        "2032-01-05T08:15:00",  # the booked one
        "2032-01-06T14:00:00",  # preferred, but MIST found it blocked
        "2032-01-07T15:30:00",  # preferred and new: the only keeper
        "2032-01-10T12:00:00",  # Saturday
    )]
    out = mod.candidates(slots, "swap", current="2032-01-05 08:15")
    assert [s["start"] for s in out] == ["2032-01-07T15:30:00"]
    hunt = mod.candidates(slots, "hunt")
    assert len(hunt) == 4 and not hunt[0]["preferred"]


def test_swap_watch_closes_inside_cancel_window(tmp_path, monkeypatch):
    entry = {"date": "2032-01-05", "time": "08:00", "id": 7,
             "swap": {"since": "2031-12-31", "until": "2032-01-15"}}
    mod = load_schedule(tmp_path, monkeypatch, {"pending": [entry]})
    _ahead(mod, tmp_path, n=1)
    assert mod.plan(date(2032, 1, 2))["swaps"]
    assert not mod.plan(date(2032, 1, 4))["swaps"]


def test_swap_replaces_the_entry_and_drops_the_watch(tmp_path, monkeypatch):
    entry = {"date": "2032-01-05", "time": "08:00", "id": 7, "provider": "[Stylist]",
             "swap": {"since": "2031-12-31", "until": "2032-01-15"}}
    mod = load_schedule(tmp_path, monkeypatch, {"pending": [entry]})
    mod.main(["swap", "--old-date", "2032-01-05", "--date", "2032-01-07",
              "--time", "15:30", "--id", "9"])
    (new,) = mod.load_state()["pending"]
    assert new == {"date": "2032-01-07", "time": "15:30", "id": 9, "provider": "[Stylist]"}
