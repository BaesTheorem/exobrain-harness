"""survey: the instruments that read a recording, on synthetic audio with known answers.
Arrays only: no ffmpeg, no network."""

import sys

import numpy as np

from conftest import REPO

sys.path.insert(0, str(REPO / "mist-music" / "modal"))

import survey  # noqa: E402

SR = survey.SR


def tone(freq: float, seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    env = np.minimum(1.0, np.minimum(t, seconds - t) / 0.01)
    return (0.5 * np.sin(2 * np.pi * freq * t) * env).astype(np.float32)


def hz(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def melody(notes: list[tuple[float, float, int]], bpm: float, lead_in: float, total_beats: float) -> np.ndarray:
    """(beat, length in beats, MIDI pitch) as sine tones."""
    beat = 60.0 / bpm
    x = np.zeros(int((lead_in + total_beats * beat + 0.5) * SR), dtype=np.float32)
    for b, d, p in notes:
        a = int((lead_in + b * beat) * SR)
        seg = tone(hz(p), d * beat)
        x[a:a + len(seg)] += seg
    return x


def test_tempo_grid_finds_the_tempo_of_a_click_track():
    rng = np.random.default_rng(1)
    bpm, lead_in = 112.0, 0.30
    x = np.zeros(int(20 * SR), dtype=np.float32)
    for k in range(int(20 / (60 / bpm / 4)) - 2):
        a = int((lead_in + k * 60 / bpm / 4) * SR)
        x[a:a + 200] += (rng.standard_normal(200) * (1.0 if k % 4 == 0 else 0.4)).astype(np.float32)
    got, off, ratio = survey.tempo_grid(x, 104, 120, step=0.05)
    assert abs(got - bpm) < 0.06
    six = 60 / bpm / 4
    assert min((off - lead_in) % six, six - (off - lead_in) % six) < 0.03     # the grid passes through the clicks
    assert ratio > 1.5


def best_score(report: str) -> float:
    return float(report.split("best start beats: ")[1].split("  ")[0].split()[-1])


def test_align_finds_the_passage_and_the_written_key():
    bpm, lead_in = 100.0, 0.5
    phrase = [(0, 1, 60), (1, 1, 64), (2, 1, 67), (3, 1, 70), (4, 2, 61), (6, 2, 65)]
    filler = [(b, 1, 62) for b in range(0, 12)] + [(b, 1, 69) for b in range(20, 32)]
    x = melody(filler + [(b + 12, d, p) for b, d, p in phrase], bpm, lead_in, 32)
    report = survey.align(x, bpm, lead_in, [(b, d, p % 12) for b, d, p in phrase], 8)
    assert "best start beats: 12 " in report
    assert "WRITTEN KEY WINS" in report
    # the control: the same phrase a tritone away is nowhere in the audio, so its best match is far weaker
    wrong = survey.align(x, bpm, lead_in, [(b, d, (p + 6) % 12) for b, d, p in phrase], 8)
    assert best_score(report) > 0.8
    assert best_score(wrong) < 0.5 * best_score(report)


def test_f0_track_names_each_sixteenth():
    bpm = 120.0
    notes = [(i * 0.25, 0.25, p) for i, p in enumerate([72, 74, 76, 77, 79, 77, 76, 74] * 2)]
    x = melody(notes, bpm, 0.5, 4)
    line = survey.f0_track(x, bpm, 0.5, [1])
    cells = line.replace("|", " ").split()[2:]
    assert cells[:8] == ["C5", "D5", "E5", "F5", "G5", "F5", "E5", "D5"]


def test_form_labels_repeated_bars_alike():
    bpm = 120.0
    bar_a = [(0, 1, 60), (1, 1, 64), (2, 1, 67), (3, 1, 72)]
    bar_b = [(0, 1, 62), (1, 1, 65), (2, 1, 69), (3, 1, 74)]
    notes = [(b + 4 * k, d, p) for k, bar in enumerate([bar_a, bar_a, bar_b, bar_a]) for b, d, p in bar]
    out = survey.form(melody(notes, bpm, 0.5, 16), bpm, 0.5)
    assert "form: A A B A" in out
