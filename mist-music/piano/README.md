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
the loudness target.

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
