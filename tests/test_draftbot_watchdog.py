"""Tests for the draft-room death detector in fantasy/draftbot/supervise.py.

INVARIANTS
  - hung() must be able to return BOTH answers. A watchdog that can only say
    "dead" fires forever; one that can only say "fine" is why the 2026-09-07
    mock sat on a dropped connection for 23 minutes without noticing. Every
    failure fixture here is paired with a healthy one as a positive control.
  - Each marker is a real observed failure, not a guess. Adding one means
    having seen it.
"""

import json

import pytest
from conftest import load_script

supervise = load_script("fantasy/draftbot/supervise.py")


@pytest.fixture
def state(tmp_path, monkeypatch):
    """Point supervise at a throwaway state.json and return a writer for it."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(supervise, "STATE", path)

    def write(text):
        path.write_text(json.dumps({"ts": "18:30:00", "url": "x", "text": text}))

    return write


# Captured verbatim from the room that dropped during the 2026-09-07 mock.
CONNECTION_FAILED = (
    "Connection Failed\n"
    "Multiple attempts to connect to the draft server have been unsuccessful.\n"
    "Exit Draft\nRetry\n"
    "ESPN Fantasy Football Draft - Expert 12-Team H2H Points PPR Mock\n"
    "RND 10 OF 16\n--:--\nPICK 114\n"
)

# A room mid-draft, long enough to clear MIN_ROOM_TEXT.
HEALTHY_ROOM = (
    "ESPN Fantasy Football Draft - Roll for First Down\n"
    "RND 3 OF 16\nPICK 27\nYou are on the clock\n"
    "QB1/4RB2/8WR1/8TE0/3K0/3D/ST0/3\n"
    "Roster Limits\nPOS\nQB\nJ. Allen\n7\nRB\nB. Hall\n13\n"
) + "player row filler. " * 20


def test_detects_dropped_connection(state):
    state(CONNECTION_FAILED)
    assert supervise.hung() == "Connection Failed"


def test_detects_hung_loading_banner(state):
    state("Loading your draft" + " padding" * 60)
    assert supervise.hung() == "Loading your draft"


def test_detects_blank_page(state):
    """The wedged room rendered zero characters and matched no marker."""
    state("")
    assert supervise.hung() == "blank page"


def test_healthy_room_is_not_flagged(state):
    """Positive control: the detector must be able to say 'fine'."""
    state(HEALTHY_ROOM)
    assert supervise.hung() is None


def test_missing_state_file_is_not_a_false_alarm(tmp_path, monkeypatch):
    """No state.json yet (driver still booting) is not a dead room."""
    monkeypatch.setattr(supervise, "STATE", tmp_path / "nope.json")
    assert supervise.hung() is None


def test_every_marker_fires_and_healthy_text_clears_all(state):
    """Each marker is load-bearing, and none of them match a healthy room."""
    for marker in supervise.HANG_MARKERS:
        state(marker + " padding" * 60)
        assert supervise.hung() == marker, f"{marker!r} did not fire"
    state(HEALTHY_ROOM)
    assert supervise.hung() is None
