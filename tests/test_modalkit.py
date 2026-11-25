"""modalkit: the scale remap, its rule for altered notes, and the note census.
No audio and no network. The tune here is a made-up line, not a real one."""

import sys

import numpy as np
import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "mist-music" / "modal"))

import modalkit as mk  # noqa: E402


def section(notes, scale="phrygianDominant", tonic=0):
    return mk.Section("t", tonic=tonic, scale=scale, bpm=100, meter=4, beats=8,
                      notes=[mk.Note(i * 0.5, 0.5, *n) for i, n in enumerate(notes)])


def pitches(sec, tonic_midi):
    return [p for _, _, p in mk.midi_notes(sec, tonic_midi)]


def test_scale_lookup_accepts_aliases_and_spelling():
    assert mk.scale("Dorian") == mk.scale("dorian")
    assert mk.scale("aeolian") == mk.SCALES["minor"]
    assert mk.scale("phrygian dominant") == mk.SCALES["phrygianDominant"]
    with pytest.raises(KeyError):
        mk.scale("blorptonic")


def test_plain_degrees_keep_their_number():
    # C Phrygian dominant 1 2 3 4 5 6 7 = C Db E F G Ab Bb; in A Dorian = A B C D E F# G
    src = section([(d, 0, 0) for d in range(1, 8)])
    dst, moves = mk.remap(src, "dorian", "A")
    assert pitches(src, 60) == [60, 61, 64, 65, 67, 68, 70]
    assert pitches(dst, 57) == [57, 59, 60, 62, 64, 66, 67]
    assert moves == []


def test_altered_note_takes_its_own_pitch_when_the_new_scale_has_it():
    # #2 and #6 of Phrygian dominant are the natural 2 and 6, which Dorian has as scale tones
    dst, moves = mk.remap(section([(2, 1, 0), (6, 1, 0)]), "dorian", "C")
    assert [(n.degree, n.acc) for n in dst.notes] == [(2, 0), (6, 0)]
    assert {m.how for m in moves} == {"absorbed"}


def test_altered_note_with_no_equal_moves_to_the_nearest_tone_same_degree_first():
    # #7 of Phrygian dominant is the leading tone. Dorian has b7 and 1 at one semitone each: the tie goes to 7.
    dst, moves = mk.remap(section([(7, 1, -1)]), "dorian", "C")
    assert (dst.notes[0].degree, dst.notes[0].acc, dst.notes[0].octave) == (7, 0, -1)
    assert moves[0].how == "nearest" and (moves[0].was, moves[0].now) == ("#7", "7")


def test_remap_output_has_scale_tones_only():
    rng = np.random.default_rng(3)
    notes = [(int(rng.integers(1, 8)), int(rng.integers(-1, 2)), int(rng.integers(-1, 2))) for _ in range(200)]
    for target in mk.MODES:
        dst, _ = mk.remap(section(notes), target, "E")
        c = mk.census([(d, p) for _, d, p in mk.midi_notes(dst, 64)], 4)
        assert mk.scale_report(c, target)["outside"] < 1e-9


def test_census_separates_dorian_from_natural_minor_and_the_control_fails():
    dorian = [(1.0, 57), (1.0, 60), (1.0, 64), (0.5, 66), (1.0, 67)]      # A C E F# G
    c = mk.census(dorian, 9)
    mine, theirs = mk.scale_report(c, "dorian")["versus"]["minor"]
    assert mine > 0.1 and theirs == 0.0
    control = [(d, p - 1 if p % 12 == 6 else p) for d, p in dorian]        # F sharp down to F
    mine, theirs = mk.scale_report(mk.census(control, 9), "dorian")["versus"]["minor"]
    assert mine == 0.0 and theirs > 0.1


def test_separators_name_the_tone_that_tells_two_modes_apart():
    sep = mk.separators("dorian")
    assert sep["minor"] == ((9,), (8,))          # the natural sixth against the flat sixth
    assert sep["mixolydian"] == ((3,), (4,))     # the minor third against the major third


def test_contour_counts_merged_steps():
    # 7 then #7 then 1 rises twice in the source; in Dorian the first step becomes a repeat
    src = section([(7, 0, -1), (7, 1, -1), (1, 0, 0)])
    dst, _ = mk.remap(src, "dorian", "A")
    assert mk.contour(src, dst) == (1, 1, 2)


def test_parse_hooktheory_reads_degrees_accidentals_and_rests():
    payload = {"song": "x", "jsonData": __import__("json").dumps({
        "keys": [{"beat": 1, "scale": "phrygianDominant", "tonic": "G"}],
        "tempos": [{"bpm": 104}], "meters": [{"numBeats": 4}], "endBeat": 9,
        "notes": [{"sd": "#6", "beat": 1, "isRest": False, "octave": 1, "duration": 0.5},
                  {"sd": "1", "beat": 2, "isRest": True, "octave": 0, "duration": 1}],
        "chords": [{"beat": 1, "root": 7, "type": 5, "isRest": False, "applied": 0, "inversion": 0,
                    "omits": [3], "borrowed": "", "duration": 2}]})}
    sec = mk.parse_hooktheory(payload)
    assert (sec.tonic, sec.scale, sec.beats, sec.bars()) == (7, "phrygianDominant", 8.0, 2)
    assert sec.notes == [mk.Note(beat=0, dur=0.5, degree=6, acc=1, octave=1)]
    assert sec.chords[0].omits == (3,)


def test_a_tab_that_changes_key_becomes_one_part_for_each_key():
    payload = {"song": "x", "jsonData": __import__("json").dumps({
        "keys": [{"beat": 1, "scale": "phrygian", "tonic": "C"}, {"beat": 5, "scale": "phrygianDominant", "tonic": "C"}],
        "tempos": [{"bpm": 110}], "meters": [{"numBeats": 2}], "endBeat": 9,
        "notes": [{"sd": "3", "beat": 1, "isRest": False, "octave": 0, "duration": 1},
                  {"sd": "3", "beat": 5, "isRest": False, "octave": 0, "duration": 1}],
        "chords": []})}
    first, second = mk.parse_hooktheory_parts(payload, name="t")
    assert (first.scale, first.start, first.beats) == ("phrygian", 0, 4)
    assert (second.scale, second.start, second.beats) == ("phrygianDominant", 4, 4)
    assert [n.beat for n in second.notes] == [4]                 # beats stay relative to the whole tab
    # the same degree 3 is E flat in the first part and E in the second; both land on the Dorian third
    for part in (first, second):
        dst, _ = mk.remap(part, "dorian", "A")
        assert pitches(dst, 57) == [60]
    with pytest.raises(ValueError):
        mk.parse_hooktheory(payload, name="t")
