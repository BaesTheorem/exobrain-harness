"""Tests for the haircut cadence gate (barber/schedule.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BARBER = Path(__file__).resolve().parent.parent / "barber"


def load_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: dict | None):
    """Import schedule.py with its state/config redirected at a temp dir."""
    spec = importlib.util.spec_from_file_location("barber_schedule", BARBER / "schedule.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations via sys.modules, so register before exec.
    sys.modules["barber_schedule"] = mod
    spec.loader.exec_module(mod)

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"interval_weeks": 6}))
    state_file = tmp_path / "state.json"
    if state is not None:
        state_file.write_text(json.dumps(state))

    monkeypatch.setattr(mod, "CONFIG_PATH", config)
    monkeypatch.setattr(mod, "STATE_PATH", state_file)
    return mod


def test_no_history_acts_immediately(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, None)
    st = mod.status(date(2026, 8, 16))
    assert st.should_act
    assert st.last_haircut is None


def test_not_due_stays_quiet(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2026-08-15"})
    st = mod.status(date(2026, 8, 16))
    assert not st.should_act
    assert st.due == date(2026, 9, 26)
    assert st.days_until_due == 41


def test_acts_inside_lead_window(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2026-08-15"})
    # Due 2026-09-26; LEAD_DAYS is 12, so 09-15 is inside the window.
    st = mod.status(date(2026, 9, 15))
    assert st.should_act
    assert st.days_until_due == 11


def test_nudges_only_once_per_cycle(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2026-08-15", "notified_cycle": "2026-09-26"},
    )
    st = mod.status(date(2026, 9, 15))
    assert not st.should_act
    assert "already nudged" in st.reason


def test_due_derives_from_haircut_not_notification(tmp_path, monkeypatch):
    """An ignored nudge must not slide the schedule later."""
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2026-08-15", "notified_cycle": "2026-09-26"},
    )
    # Well past the due date and still ignored: due stays put, and because the
    # cycle is unchanged we do not re-nudge -- but the date has not drifted.
    st = mod.status(date(2026, 10, 20))
    assert st.due == date(2026, 9, 26)
    assert st.days_until_due == -24


def test_record_resets_the_cycle(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": "2026-08-15", "notified_cycle": "2026-09-26"},
    )
    mod.main(["record", "--date", "2026-09-26", "--barber", "Razor Nick"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["last_haircut"] == "2026-09-26"
    assert state["notified_cycle"] is None
    assert state["history"][-1]["barber"] == "Razor Nick"


def test_pending_appointment_silences_the_daily_job(tmp_path, monkeypatch):
    """The bootstrap case: no history, but a cut is already booked."""
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": None, "pending": "2026-08-29"})
    assert not mod.status(date(2026, 8, 17)).should_act
    assert not mod.status(date(2026, 8, 29)).should_act  # the day itself


def test_job_wakes_again_after_the_appointment_passes(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": None, "pending": "2026-08-29"})
    st = mod.status(date(2026, 8, 30))
    assert st.should_act
    assert st.reason == "no haircut on record yet"


def test_pending_does_not_suppress_a_later_due_cycle(tmp_path, monkeypatch):
    """A spent appointment must not silence the next cycle forever."""
    mod = load_schedule(
        tmp_path, monkeypatch, {"last_haircut": "2026-08-29", "pending": "2026-08-29"}
    )
    # Next due 2026-10-10; inside the lead window and the appointment is past.
    st = mod.status(date(2026, 10, 1))
    assert st.should_act
    assert st.due == date(2026, 10, 10)


def test_record_clears_the_pending_appointment(tmp_path, monkeypatch):
    mod = load_schedule(
        tmp_path,
        monkeypatch,
        {"last_haircut": None, "pending": "2026-08-29", "pending_barber": "Razor Nick"},
    )
    mod.main(["record", "--date", "2026-08-29", "--barber", "Razor Nick"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["pending"] is None
    assert "pending_barber" not in state
    assert state["last_haircut"] == "2026-08-29"


def test_search_window_never_starts_in_the_past(tmp_path, monkeypatch):
    mod = load_schedule(tmp_path, monkeypatch, {"last_haircut": "2026-06-01"})
    today = date(2026, 8, 16)
    start, end = mod.search_window(today)
    assert start > today
    assert end > start
    assert (end - start) <= timedelta(days=90)
