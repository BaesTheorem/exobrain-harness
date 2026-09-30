#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mido>=1.3", "numpy>=1.26", "scipy>=1.11"]
# ///
"""Last Light of September, for solo piano.

Written on 30 September 2026, the last day of the month. D-flat major, about
three minutes. The score is in C major for legibility and sounds a half step
higher (transpose=1).

  Intro  1-4    falling seventh chords, left hand alone
  A      5-12   the theme: a rising sixth, then a sigh
  A'     13-20  the theme with a second voice, climbing by step to a half cadence
  B      21-28  A minor over a falling bass while the melody climbs against it
  A''    29-38  the theme in octaves, the borrowed A-flat, then a deceptive
                cadence that walks up through A-flat and B-flat to C
  Coda   39-44  the opening chords again, the sigh falling away, a last high E

    uv run mist-music/piano/last_light_of_september.py          # MIDI + MP3 in tmp/audio/
    uv run mist-music/piano/last_light_of_september.py --dump   # print every bar's voicing
    uv run mist-music/piano/last_light_of_september.py --tuning just   # adaptive just intonation
"""

import pianokit as pk

INTRO = pk.section([
    # chords                    melody                              bpm  mel  acc
    ("Fmaj7@F2",                "r:4",                              60,  54,  40),
    ("Em7@E2",                  "r:4",                              61,  54,  41),
    ("Dm7@D2",                  "r:4",                              62,  54,  42),
    ("Cadd9@C2",                "r:3.5 G4:.5",                      62,  56,  42),
])

THEME = pk.section([
    ("Fmaj7@F2",                "E5:1.5 F5:.5 E5:1 C5:1",           66,  61,  37),
    ("G6@G2",                   "D5:3 r:.5 G4:.5",                  66,  61,  37),
    ("Em7@E2",                  "D5:1.5 E5:.5 D5:1 B4:1",           66,  63,  38),
    ("Am7@A2",                  "C5:3 r:.5 A4:.5",                  66,  61,  37),
    ("Dm7@D2",                  "F5:1 G5!:1 A5:1.5 F5:.5",          66,  67,  40),
    ("G7sus4@G2:2, G7@G2:2",    "G5:1.5 F5:.5 D5:1 B4:1",           66,  67,  40),
    ("C/G@G2:2, G7@G2:2",       "E5:2 D5:2",                        66,  63,  38),
    ("Cadd9@C2",                "C5:3 r:.5 G4:.5",                  65,  59,  37),
])

THEME_AGAIN = pk.section([
    ("Fmaj7@F2",                "E5:1.5 F5:.5 E5:1 C5:1",           66,  65,  39),
    ("G6@G2",                   "D5:2 E5:.5 D5:.5 B4:.5 G4:.5",     66,  65,  39),
    ("Em7@E2",                  "D5:1.5 E5:.5 D5:1 B4:1",           67,  67,  41),
    ("Am7@A2",                  "C5:3 r:.5 A4:.5",                  66,  67,  41),
    ("Dm7@D2",                  "F5:1 G5!:1 A5:1.5 F5:.5",          68,  72,  44),
    ("Em7@E2",                  "G5:1 A5!:1 B5:1.5 G5:.5",          69,  76,  47),
    ("Fmaj7@F2",                "A5:1 B5!:1 C6:1.5 A5:.5",          69,  80,  50),
    ("E7sus4@E2:2, E7@E2:2",    "B5:2 G#5:2",                       67,  73,  45),
], rh="duet")

MINOR = pk.section([
    ("Am@A2",                   "E5:1 A5:1.5 G5:.5 E5:1",           64,  59,  37),
    ("Em/G@G2",                 "G5:1.5 E5:.5 B4:2",                65,  60,  37),
    ("Fmaj7@F2",                "C5:1 F5:1.5 E5:.5 C5:1",           66,  62,  38),
    ("C/E@E2",                  "E5:1.5 D5:.5 C5:2",                66,  62,  38),
    ("Dm7@D2",                  "D5:1 A5:1.5 G5:.5 F5:1",           68,  69,  42, {"lh": "wave2", "rh": "duet"}),
    ("Am/C@C2",                 "E5:1 C6:1.5 B5:.5 A5:1",           69,  76,  47, {"lh": "wave2", "rh": "duet"}),
    ("Bm7b5@B1",                "F5:1 D6:1.5 C6:.5 B5:1",           70,  83,  52, {"lh": "wave2", "rh": "duet"}),
    ("E7@E2",                   "A5!:1 G#5:1 B5:1.5 G#4+G#5:.5",    67,  87,  56, {"lh": "rise", "rh": "duet"}),
])

CLIMAX = pk.section([
    ("Fmaj7@F2",                "E5:1.5 F5:.5 E5:1 C5:1",           62,  89,  54),
    ("G6@G2",                   "D5:3 r:.5 G4:.5",                  62,  86,  52),
    ("Em7@E2",                  "D5:1.5 E5:.5 D5:1 B4:1",           63,  87,  52),
    ("A7@A2",                   "C#5:1.5 D5:.5 E5:1 G5:1",          63,  89,  54),
    ("Dm7@D2",                  "F5:1.5 E5:.5 D5:1 A5:1",           62,  92,  56),
    ("Fm6@F2",                  "Ab5:2 G5!:1 F5:1",                 60,  94,  56),
    ("C/G@G2:2, G7@G2:2",       "E5:2 D5:2",                        60,  85,  50),
    ("Abmaj7@Ab2",              "C5:2 Eb5:1.5 F5:.5",               58,  83,  48),
    ("Bb69@Bb2",                "G5:2 F5:1 D5:1",                   57,  79,  46),
    ("Cadd9@C2",                "C5:4",                             55,  73,  42),
], lh="climax", rh="octaves")

CODA = pk.section([
    ("Fmaj7@F2",                "E5:1.5 F5:.5 E5:2",                56,  63,  39),
    ("Em7@E2",                  "D5:1.5 E5:.5 D5:2",                55,  61,  38),
    ("Dm7@D2",                  "C5:1.5 D5:.5 C5:2",                53,  59,  38),
    ("Fm6@F2",                  "Ab4:2 G4!:2",                      50,  57,  37),
    ("Cadd9@C2",                "r:1 G5:1 C6:1 D6:1",               47,  55,  37, {"ring": 2}),
    ("Cadd9@C2",                "E6:4",                             42,  55,  37, {"lh": "rolled", "ring": 1}),
], lh="calm")

PIECE = pk.Piece(
    title="Last Light of September",
    sections=[INTRO, THEME, THEME_AGAIN, MINOR, CLIMAX, CODA],
    transpose=1,
    key="Db",
    phrases=(1, 5, 9, 13, 17, 21, 25, 29, 33, 39),
    rits=(
        ((4, 3), (5, 1), 0.85),    # a breath before the theme
        ((12, 2), (13, 1), 0.88),
        ((16, 3), (17, 1), 0.94),
        ((20, 2), (21, 1), 0.78),  # the half cadence
        ((24, 3), (25, 1), 0.94),
        ((28, 1), (29, 1), 0.68),  # broaden into the return
        ((32, 3), (33, 1), 0.95),
        ((34, 1), (34, 3), 0.90),  # lean on the A-flat
        ((37, 1), (39, 1), 0.80),
        ((42, 1), (43, 1), 0.88),
        ((44, 1), (45, 1), 0.80),
    ),
    holds=(
        ((20, 4.9), 0.30),
        ((28, 4.9), 0.20),
        ((38, 4.9), 0.35),
        ((44, 4.5), 1.00),
    ),
    comment=(
        "Composed and performed in Python with pianokit. Piano: Salamander Grand Piano V3 "
        "by Alexander Holm, CC BY 3.0, via FreePats."
    ),
)

if __name__ == "__main__":
    pk.main(PIECE)
