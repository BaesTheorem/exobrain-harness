"""celtic: the clock, the scale steps, and the Band's bookkeeping. No audio is rendered.
Needs scipy and mido: `uv run --with scipy --with mido --with pytest pytest tests/test_modal_celtic.py`."""

import sys

import pytest

from conftest import REPO

pytest.importorskip("scipy")
pytest.importorskip("mido")
sys.path.insert(0, str(REPO / "mist-music" / "modal"))

import celtic as ck  # noqa: E402


def test_clock_delays_the_second_sixteenth_of_each_pair():
    straight, lilted = ck.Clock(120, lilt=0.5, lead_in=0), ck.Clock(120, lilt=0.6, lead_in=0)
    six = 60 / 120 / 4
    assert straight.t(3) == pytest.approx(3 * six)
    assert lilted.t(2) == pytest.approx(2 * six)                 # the first of a pair stays on the grid
    assert lilted.t(1) == pytest.approx(1.2 * six)               # the second moves late
    assert lilted.t(16) == pytest.approx(16 * six)


def test_scale_steps_cut_and_tap_stay_in_the_dorian_scale():
    a = 9                                                        # A Dorian: A B C D E F# G
    assert [ck.step(69, a, k) for k in range(8)] == [69, 71, 72, 74, 76, 78, 79, 81]
    assert ck.step(69, a, -1) == 67
    assert ck.cut(71, a) == 3                                    # B up two steps is D
    assert ck.tap(79, a) == 1                                    # G down one step is F sharp


def test_band_rhythm_counts_every_note_and_uses_the_riff():
    b = ck.Band(ck.Clock(110))
    b.rhythm(32, "X.ur", {0: "Am"}, riff={3: (43, 3.0)}, bz=0)
    pitches = sorted(p for _, _, p in b.written)
    assert pitches == sorted(ck.DADGAD["Am"] + ck.DADGAD["Am"][-3:] + [43])
    assert [(t.slot, t.pitch) for t in b.gtr_single] == [(35, 43)]
    assert b.bouz.ev == []


def test_substitute_changes_tones_and_strummed_notes_by_position():
    b = ck.Band(ck.Clock(110))
    b.lead(b.fiddle, ck.Tone(0, 2, 66))                          # F sharp at slot 0
    b.lead(b.fiddle, ck.Tone(40, 2, 66))                         # and at slot 40
    b.rhythm(40, "X", {0: "D"}, bz=0)                            # a D chord (with F sharp) at slot 40
    b.substitute(lambda slot, p: p - 1 if slot >= 32 and p % 12 == 6 else p)
    assert [t.pitch for t in b.fiddle] == [66, 65]
    ons = sorted(m.note for _, _, m in b.gtr.ev if m.type == "note_on")
    offs = sorted(m.note for _, _, m in b.gtr.ev if m.type == "note_off")
    assert ons == offs == sorted(p - 1 if p % 12 == 6 else p for p in ck.DADGAD["D"])
