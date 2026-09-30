# loops

Pieces that are loops with no seam, and `loopkit`, the engine that renders them.

`loopkit` is additive synthesis in numpy. It has three properties that a
sampler or a MIDI render cannot give:

- **Shepard stacks.** Each note is one tone at all octaves. A fixed bell
  curve over log frequency sets the level of each octave copy. Thus a pitch
  class has no octave, and a line can go up (or down) with no end and come
  back to its start.
- **One period, rendered circularly.** The piece renders into one buffer of
  one period. When the tail of a note goes past the end of the buffer, it
  continues at the start. The reverb is a circular convolution, and the
  high-pass filter, the shelf, and the limiter also wrap. Thus the output is
  periodic to the sample.
- **Pure tuning that closes.** Pitches are points of the 5-limit lattice
  (powers of 3 and 5), so chords can be pure. A pure-tuned cycle cannot close,
  because a power of 3 is not a power of 2. A glide that is the same for all
  notes lifts the full texture by the missing comma in each cycle.

## Run a piece

```bash
uv run mist-music/loops/descendendo_ascendit.py            # render to tmp/audio/
uv run mist-music/loops/descendendo_ascendit.py --dump     # the score and the score checks
uv run --with matplotlib mist-music/loops/descendendo_ascendit.py --check    # render, then measure
uv run --with matplotlib mist-music/loops/descendendo_ascendit.py --measure  # measure the last render
```

`--check` renders the piece, then measures it:

- the triad in each bar of the mix against the score, with a control that moves the labels by one bar
- the seam of the loop in the FLAC file and in the loop window of the MP3, with a control window that is 37 samples too long
- the loudness and the true peak
- a spectrogram of the first cycle

Each render writes two files to `tmp/audio/`:

| File | Contents |
|---|---|
| `<slug>-loop.flac` | One period, lossless. It loops with no seam in a gapless player. |
| `<slug>.mp3` | The period, with 2 s of its own tail before it and 2 s of its own head after it. |

An MP3 decoder adds a delay and padding at the edges of the file. The 2 s of
roll keep those edges out of the loop window, which is `[2, 2 + period)`
seconds. In the MIST Console, the embed `![title](/abs/path.mp3#loop=2,218)`
plays that window as a gapless loop through Web Audio.

| File | Piece |
|---|---|
| `descendendo_ascendit.py` | *Descendendo ascendit*, 30 September 2026. A strange loop through all 24 keys. The period is 216 s. |

## Write a new piece

1. Make the `Layer`s. Each layer has a `Tone` (its partials, envelope, and decay), the center and the width of its Shepard envelope, and a reverb send.
2. Make the `Note`s. A note has a layer, an onset in the period, a length in seconds, and a pitch as log2 of Hz, in any octave. `lattice(a, b)` gives log2 of 3^a 5^b.
3. Give the period and the glide to the `Loop`. The glide is the drift of the tuning in one period. Then use `render()`, `mix()`, `master()`, and `write_outputs()`.
4. Write the balance as a loudness target for each layer. Then set each gain from the measured stem (`lufs_ungated`), as the piece does.

The period must be a whole number of samples at 48 kHz.

## The stem cache

`Loop.render()` renders each layer in its own process and saves each stem in
`tmp/loopkit-cache/<slug>/` (83 MB for a 216 s stereo stem). The file name
contains a hash of all the data that shapes the stem: the layer, its notes,
the period, the glide, and the seed. Each layer has its own random stream, so
a change to one layer does not change the other layers. Thus a change to the
mix (gains, reverb, EQ) or to one layer renders only the changed layers.

## Measured facts

- The first render of *Descendendo ascendit* (1116 notes, 216 s) took 9 to 10
  minutes in one process and 9.5 minutes in five processes, while other work
  used the CPU. A mix-only run from the cache takes approximately 1 minute,
  checks included. Peak memory was 1.4 GB.
- The chord check reads the pitch classes of beats 1 and 2 of each bar through
  a Hann window. The just-tuned notes are less than 40 cents from equal
  temperament, so each note stays in its own pitch class. Name the chords from
  the first cycle: the raw chain falls one comma per cycle (the glide
  compensates), and in the third cycle its names rounded to the wrong key.
  That fault made the first check report 44 of 72 bars as incorrect.
- The seam: in the FLAC file and in the MP3 window, the sample step across the
  wrap is 0.017. The 99.99th percentile of the steps in the period is 0.067,
  and a window that is 37 samples too long gives a step of 0.149.
- Above 8 kHz, the 10 ms at the wrap peak 10 dB above the median. The cause
  is the onsets on the downbeat of bar 1 (eight bells, a harp pluck, organ
  chiff), not a click. In that band, the wrap peaks at -37 dBFS, and the
  other downbeats with a peal peak from -42 to -33 dBFS.
