# piano

Solo piano pieces written in Python, and `pianokit`, the engine that performs
and renders them.

A piece is a score in a Python file. Each bar gives its chords with a bass
note, the melody as `pitch:beats` tokens, a left-hand pattern, a right-hand
texture, a tempo, and two dynamics. `pianokit` voices the chords and plays the
patterns. Then it adds a performance:

- rubato across each phrase, and ritardandi and holds at the cadences
- legato pedal in the left hand
- a melody that sounds 12 ms before the accompaniment
- seeded variation in time and velocity

The output is a performance MIDI, a quantized score MIDI, and an MP3 of the
Salamander Grand Piano in a synthesized hall.

## Run a piece

```bash
uv run mist-music/piano/last_light_of_september.py             # MIDI + MP3 in tmp/audio/
uv run mist-music/piano/last_light_of_september.py --dump      # each bar's voicing and melody
uv run mist-music/piano/last_light_of_september.py --balance   # melody against accompaniment
uv run mist-music/piano/last_light_of_september.py --midi-only
```

`uv` installs mido, numpy, and scipy from the header of the script. FluidSynth
and ffmpeg come from Homebrew. `--wet` sets the hall level and `--lufs` sets
the loudness target. `--tuning just` renders the same performance in adaptive
just intonation, to files with a `-just` suffix.

| File | Piece |
|---|---|
| `last_light_of_september.py` | *Last Light of September*, 30 September 2026. D-flat major, 2:57. |

## Write a new piece

Copy a piece file and replace its sections. The token grammar and the pattern
names are in the docstring of `pianokit.py`.

1. Run `--dump` and read the voicings. The harmony check prints a warning for each long or strong-beat melody note that is not in its chord.
2. Mark an intended non-chord tone with `!`, for example `G5!:1`.
3. Render with `--balance`. In each section with a melody, the melody must be 3 to 5 LU above the accompaniment.
4. If the melody is too low, decrease the accompaniment velocities before you increase the melody.

## Just intonation

With `--tuning just`, the piano retunes for each chord. The root of the chord
keeps its equal-tempered pitch, so the piece cannot move out of tune over its
length. Each other note takes a 5-limit ratio above the root: the major third
is 5:4 (13.7 cents below equal temperament), the fifth 3:2, and the minor third
6:5. Chord sevenths use 9:5. The 7:4 seventh is purer in the chord, but it is
31 cents flat. In this piece, it made a melody step of only 153 cents (bars 32
to 33).

`pianokit` writes the tunings into the MIDI file as MIDI Tuning Standard
messages, 3 ms before each chord. The messages are non-real-time, so a note
that sounds when a message arrives keeps its pitch.

Measured on the D-flat major chord, one note at a time:

| Overtones that meet | Equal temperament | Just intonation |
|---|---|---|
| Major third, D-flat 5th vs F 4th | 15.8 beats/s | 4.5 beats/s |
| Minor third, F 6th vs A-flat 5th | 22.0 beats/s | 3.8 beats/s |
| Fifth, D-flat 3rd vs A-flat 2nd | 0.5 beats/s | 0.9 beats/s |

The thirds continue to beat, because piano overtones are sharper than
whole-number multiples of the fundamental frequency. On this piano, a major
third with no beats is approximately 20 cents below equal temperament. A
Sethares roughness sum for all overtone peaks did not find the difference, and
it also missed a mistuned control chord. Measurements of single overtone pairs
found it.

## The soundfont

`pianokit` uses the FreePats SF2 of the Salamander Grand Piano (a Yamaha C5,
16 velocity layers, CC BY 3.0). It expects the bank in
`~/Library/Audio/Sounds/Banks/SalamanderGrandPiano-SF2-V3+20200602/`:

```bash
curl -LO "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SF2-V3+20200602.tar.xz"
tar -xJf SalamanderGrandPiano-SF2-V3+20200602.tar.xz -C ~/Library/Audio/Sounds/Banks/
```

The SF2 is 1.27 GB, and FluidSynth holds all of it in memory during a render.
`--soundfont` selects a different bank. Attribution for rendered audio is in
`CREDITS`.

## Measured facts

- The velocity curve of this bank is steep at the soft end. Against velocity 120, velocity 20 is -49.5 dB, 30 is -38.5 dB, 40 is -29.8 dB, and 60 is -19.1 dB. Accompaniment below velocity 37 becomes almost silent.
- The pedal keeps the arpeggio notes sounding together, so their loudness increases. With a difference of 8.5 dB for each note, the melody and the accompaniment measured the same loudness. A difference of approximately 14 dB for each note gives the melody 4 to 5 LU.
- The hall is synthesized: band-limited noise with its own decay time in each band. The OpenAIR library of impulse responses gives no download links.
