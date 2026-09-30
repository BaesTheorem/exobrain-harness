# mist-vid

mist-vid makes a music video from the footage of a movie. You write the edit as a
YAML file, and each cut attaches to the song: a bar, a beat, a lyric line or a time
in seconds.
The renderer composites the frames on the GPU (OpenGL through moderngl) and sends
them to ffmpeg.

The compositor supplies these parts:

- Colour grades as 3D LUTs, with bloom, halation, film grain, gate weave and a vignette.
- Transitions from gl-transitions, plus a page curl with a paper back side.
- Slow motion with RIFE frame interpolation.
- Gold-leaf and printer's-ink typography, and aged paper title pages.
- Light leaks, flashes, double exposures and letterbox bars.
- An audio mix that levels the dialogue and makes the song quieter below each line.

The first project was a Princess Bride music video (September 2026). The tool has no
parts that only work with that movie.

## Setup

```bash
uv venv --python 3.12 mist-vid/.venv
uv pip install --python mist-vid/.venv/bin/python -r mist-vid/requirements.txt
mist-vid/bin/fetch-assets
```

The fetcher downloads these assets into `assets/`, which git ignores:

| Asset | Licence |
|---|---|
| gl-transitions | MIT, with a licence in each shader header |
| IM Fell and Cinzel Decorative fonts | OFL |
| ambientCG Paper001 texture | CC0 |
| Kenney RPG Audio and Impact Sounds | CC0 |
| rife-ncnn-vulkan (macOS build), with the v4.6 model only | MIT |

The tool also needs `ffmpeg`, and `whisper-cli` with a whisper model. Set the model
path with `MIST_VID_WHISPER`. Word timing uses `large-v3-turbo`.

## Workflow

Run all commands from the project folder. All outputs go into `work/`.

1. Make a proxy and find the shots. Then make the contact sheets.

   ```bash
   mist-vid proxy "/path/movie.mp4"
   mist-vid shots
   mist-vid sheets --srt "/path/movie.en.srt"
   ```

2. Catalogue the shots. Send one agent for each group of approximately 180 shots (15 sheets).
   Each agent reads the sheets and writes `work/catalog/part_N.json`. The schema for
   one shot follows:

   ```json
   {"shot": 55, "chars": ["Buttercup"], "desc": "max 20 words", "framing": "CU",
    "camera": "static", "motion": 1, "talk": false, "mood": "romantic",
    "energy": 2, "beauty": 5, "mv": 5, "hero": true, "tags": ["kiss", "sunset"],
    "light": "golden", "notes": "best sub-range, eyeline, problems"}
   ```

   Give the agents a character list. Tell them to write descriptions, and to quote
   only short, famous lines. The harness does not let subagents write report files, so each
   agent returns its segment summary in its reply. Then query the catalog:
   `mist-vid cat --hero`, `mist-vid cat --range 38-41 --min-mv 4`, and
   `mist-vid strip 592,1396`.

3. Map the song.

   - `mist-vid beats song.mp3` writes the beat and downbeat grids.
   - To get lyric timings, align the song against the movie's end credits with
     `mist-vid align`. The subtitle times then map onto the album track. A jump in
     the lag shows that the movie edited the song.
   - If the song is not in the movie, run whisper on a demucs vocal stem.
   - Keep the lyric text in files. Scripts can read the text, but do not write it in
     chat or in tool output.

4. Get the dialogue timings with `mist-vid words movie.mp4 150:9`. Use short windows
   only. Compare the results with the voice-energy spans before you cut on a word.

5. Write `edit.yaml`. The section "Edit file reference" below gives the grammar.

6. Check the edit, render it, and examine the result:

   ```bash
   mist-vid check edit.yaml
   mist-vid audio edit.yaml -o work/mix.wav
   mist-vid render edit.yaml -o work/preview.mp4 --preview --audio work/mix.wav
   mist-vid review work/preview.mp4 edit.yaml work/rev
   mist-vid hear work/mix.wav 0-18 101-110
   mist-vid render edit.yaml -o final.mp4 --hevc-q 68 --audio work/mix.wav
   ```

   A preview uses the VideoToolbox H.264 encoder. `--hevc-q 68` encodes the delivery
   file with VideoToolbox HEVC at GPU speed (approximately 15 Mbit/s with film
   grain). Without a flag, the render uses libx264 with the slow preset at CRF 15.
   That setting spends approximately 60 Mbit/s on grain and runs at approximately
   5 frames per second.

## Edit file reference

The `project` section names the source, the song and the analysis files:

```yaml
project:
  source: "/path/movie.mp4"
  src_fps: [2997, 125]          # the movie's frame rate, as a fraction
  src_size: [1920, 1040]
  src_frames: 141906
  size: [1920, 1080]
  fps: [24000, 1001]
  song: "audio/song.mp3"
  song_at: 25.6                 # the output second where song time 0 plays
  beats: work/beats.npy
  downbeats: work/downbeats.npy
  lyrics: work/lyric_timing.json
  shots: work/shots.csv
  pic: [0, 20, 1920, 1040]      # the picture rectangle in the canvas
  grade: storybook
  finish: {bloom: 0.2, halo: 0.08, grain: 0.032, vignette: 0.32}
```

Times are anchors:

| Anchor | Meaning |
|---|---|
| `o12.5` | output seconds |
| `s145.2` | song seconds |
| `b64`, `b64.5` | beat 64, and the point halfway to beat 65 |
| `B12`, `B12.5` | the downbeat of bar 12, and beat 3 of that bar |
| `L27`, `L27e` | the start and the end of lyric line 27 |
| `B12-2f`, `L3+0.25`, `B20+1b` | an anchor with an offset in frames, seconds or beats |

Source points are `1234.5` (movie seconds), `"#592"` (the start of shot 592),
`"#592+1.2"` (1.2 s into that shot) or `"#592@0.5"` (the middle of that shot).

The `track` is a list of clips, one after the other:

```yaml
track:
  - {src: "#54+0.05", to: B17, speed: 0.7, rife: true, grade: golden, zoom: [1.0, 1.09]}
  - {src: "#55+0.26", to: B19, tx: "dream 0.9", look: {exposure: 0.3}}
  - {card: {bg: paper, items: [{text: "Chapter One", face: canon-it, size: 150, style: gold}]}, to: B01,
     tx: "page 1.35 start"}
```

- A clip ends at `to` or after `len` (`2b`, `1.5s`, `36f`). It starts where the clip
  before it ends.
- `tx` is the transition into the clip: a name, a duration and an alignment
  (`center`, `start` or `end`). The names are `dissolve`, `dream`, `page`, `flip`,
  `burn`, `melt`, `zoom`, `blur`, `whip`, `flash`, `dip` and `dipwhite`. The name of
  a gl-transitions file is also permitted.
- A transition needs handles. A handle cannot go beyond its source shot. Thus a handle
  that is too long holds the first or the last frame of the shot. `mist-vid check`
  shows these holds.
- The grades are `storybook`, `golden`, `dawn`, `night`, `castle`, `ember`,
  `despair`, `dream`, `bedroom`, `sepia` and `neutral`.

The `layers` section adds double exposures above the track. The `overlays` section
adds text, ornaments, light leaks (`leak`) and flashes. The `finish_keys` section
sets keyframes for bloom, halation, fades and letterbox bars. In the `audio` section,
a `song` entry puts the song on the timeline, a `dlg` entry adds a levelled slice of
the movie's centre channel, and `sfx` and `synth` entries add sound effects. A `dlg`
entry makes the song quieter by its `duck` value, in dB.

## Notes

- Whisper's word times move by up to a second on long windows. A short window
  (under 10 s) that agrees with the energy spans and the subtitle times is usually
  accurate.
- End credits often shorten a song. For this reason, map the subtitle times through
  `align`, and do not use one fixed offset.
- A source point one frame before a shot boundary belongs to the shot before it,
  and the clip then holds its frame. Use a point after the boundary.
- RIFE runs at approximately 2 frames per second at 1080p on an M1. At 4x
  interpolation, 10 s of slow motion takes approximately 8 minutes. The cache is in
  `work/cache/rife`.
- The renderer puts row 0 of each image at the top. The gl-transitions wrapper
  flips the y axis for the shader.
- The model output filter blocks text that repeats song lyrics. Let scripts read and
  render lyric text from files, and keep the text out of chat and out of tool
  output.
- Keep the project files for copyrighted movies outside this repo. Only the tool
  goes in git.
