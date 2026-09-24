---
name: animate
description: "Make hand-painted 2D animated videos and music videos in code: p5.js + p5.brush watercolour, the Clawd character rig, rendered frame by frame in headless Chrome, optionally synced to a song MIST generated. Use when Alex says 'animate', 'make an animation', 'animated video', 'music video', 'cartoon', 'make a video of Clawd', 'animate this song', 'a video like the P(doom) one', or wants a short animated clip, loop or GIF-style piece."
metadata:
  kit: "~/Documents/claude-animation (fork of JohnHeibel/ClaudeAnimationBase, MIT; upstream remote = upstream)"
  guide: "~/Documents/claude-animation/ANIMATION_GUIDE.md (rules, workflow, full API)"
  song_sync: "~/Documents/claude-animation/bin/song-sync (uv + librosa)"
  reference_video: "github.com/JohnHeibel/PDoomVideo (156 s, 9 chapters, parallel subagents)"
---

# /animate

Videos are code. Each frame is a pure function of time `t`, painted with p5.brush in `studio.html`, captured by `render.mjs` through headless Chrome, and encoded with ffmpeg. There's no video model involved: Opus writes the scenes, renders contact sheets, looks at them and fixes what it sees.

**Read `~/Documents/claude-animation/ANIMATION_GUIDE.md` before writing any scene code.** It is the spec: the rules (handmade medium, no text, something happens in every shot, transitions at every seam), the storyboard format, the review loop and the whole API. This skill covers only how the kit fits into MIST.

## When MIST herself is in the video

Her form is the crystal pack, not a p5.brush drawing: `~/Documents/mist-anims` (see the Design section of CLAUDE.md). Take a clip from `dist/webm/<look>/<anim>.webm` (VP9 with alpha) and composite it over the rendered frames with ffmpeg (`overlay` filter, or `-filter_complex "[0][1]overlay=x:y"`), or for a standalone MIST piece skip this kit and write the scene in `src/anims.js` there. New moods or poses go into that repo so they stay on model.

## Performance on this Mac

On the M1 Air's Metal GPU (`--use-angle=metal`) frames take about 100–275 ms each, so an 11 s clip renders in about a minute. That is well inside the guide's 2.5 s/frame budget, so the watercolour fills can stay. RAM is the tighter limit on 8 GB: keep `--workers` at 2–3 for `--frames`.

## Workflow

1. **Project.** Each video gets its own scene file, `src/scenes/<slug>.js`, and its script tag replaces `demo.js` in `studio.html`. For anything bigger than a one-off, branch the kit (`git checkout -b video/<slug>`) so `main` stays a clean base that can pull from `upstream`.
2. **Music (optional).**
   - Generate a song with `/music` (MIST Studio on :5032 or `mist-music gen`). **Set the BPM explicitly** in the request. Tempo detection on the finished audio is unreliable, and a tempo you chose yourself is ground truth.
   - Copy the song into `assets/`. Audio there is gitignored.
   - `bin/song-sync assets/song.mp3 --bpm=<bpm>` writes `duration`, `bpm`, `offset` (first beat) and `audio` into `src/config.js`. For a song you didn't generate, run it without `--bpm` first. It prints three tempo candidates, and the true one may not be first (on P(doom) it came third). Pick by counting beats against the audio.
   - Lyrics: run the `lyrics-video/` alignment (`/music` skill, whisper + `build_ass.py`), then pass `--lyrics=<work>/timings.json` to get `LYRICS` cue times in `src/lyrics.js`. Use them to act each line and cut on it. The kit's rule is no on-screen text; a karaoke bar is a deliberate exception, and only when Alex asks for one.
3. **Storyboard first.** Write `STORYBOARD.md` in the guide's format (logline, world, motif, arc, shots with timed reads) and check it against the guide's checklist before writing code. For a music video, give each musical phrase its own shot and put the cuts on bar lines.
4. **Build and review, one shot at a time.** Use `--sheet` for the shape of a shot, `--strip` for every frame of a move or transition, and `--crop` for faces. Read every image. This review loop is what makes the result good, so do the full budget the guide asks for.
5. **Parallelise long pieces.** For videos over roughly 30 s, follow the P(doom) pattern:
   - write a chapter brief like its `ANIMATION_GUIDE.md`;
   - give each chapter file to a subagent, each running its own sheets;
   - the subagents only touch their own files, and shared files belong to the orchestrator.
   Run the subagents in the foreground: skill-heavy agents in the background fail without reporting it.
6. **Render.** Short pieces: `node render.mjs --clip --out=out/video.mp4`. Long ones: `node render.mjs --frames --workers=3`, which can resume, then `node render.mjs --encode --audio=assets/song.mp3`.
7. **Sound effects.** Every cartoon needs them, so do this by default.
   - Write `src/scenes/<slug>.sfx.json` with cue times taken from the scene's own constants (`beat(n)`, landing times, and so on). For things driven by physics, compute the hit times with the same formula the scene uses, like the goo splats in `video/dungeon`.
   - Sources, in order: Kenney's CC0 audio packs (kenney.nl: RPG Audio, Impact Sounds, Sci-Fi Sounds, Digital Audio, Interface Sounds; scrape the `.zip` link from each asset page), then UI SFX (CC0), then the mixer's built-in synths (`slide`, `whoosh`, `bubbles`, `tweet`, `hum`). Copy only the files you use into `assets/sfx/` and keep the license alongside them.
   - `bin/sfx-mix <sheet> --video=out/<slug>.mp4 --out=out/<slug>_sfx.mp4` mixes and muxes without re-rendering the frames.
   - You can't hear the mix, so measure it. Render the effects alone (set `music` to null) and look at the waveform: a solid block is a sustained tone that's too loud. Compare `ebur128` loudness for effects alone against music alone and keep them within about 2 LU; the first dungeon pass had effects 5.5 LU over the music. Check the final file's true peak is below 0 dBFS.
8. **Deliver.**
   - Copy the MP4 to `~/Documents/Exobrain harness/tmp/video/<slug>.mp4` and embed it as `![<title>](<that raw path>)`. The Console plays videos from under the harness; don't percent-encode the path.
   - Use a new filename for each version.
   - Credit a Kevin MacLeod track per the CLAUDE.md music rule.

## Gotchas

- `npm install` once per fresh clone. If it's missing, render.mjs dies with `ERR_MODULE_NOT_FOUND: puppeteer-core`.
- Frames render in parallel and out of order. No `Math.random()` and no state carried between frames: use `hash(i)` and the kit's seeded helpers.
- The renderer never plays audio, so test runs are already silent. Show results through the Console embed; don't `open` them in a player that starts playing out loud.
- Headless Chrome here uses the real GPU, not the `--headless=new` screen-flash path that `/browser-render` warns about.
- Pull kit fixes with `git fetch upstream && git merge upstream/main` on `main`.
- **Run song-sync on the trimmed excerpt you'll use, not the full track.** On "Carefree" the full-song offset came out 0.38 s off. song-sync scans the beat phase against onset energy and prints how much stronger the beat is than the half-beat. Under 1.25x, check the offset by hand. For Kevin MacLeod tracks the true BPM is in `https://incompetech.com/music/royalty-free/pieces.json` (`bpm` field).
- **A sheet showing the kit's placeholder (a smiling Clawd on blank paper) means the scene file threw.** Run `node --check src/scenes/<slug>.js`.
- **Match the effective size across cuts** (`u × zoom`) and end a moving thing's path in shot A where shot B picks it up on screen. Otherwise a cut on action reads as a jump.
- Wand or prop tips: compute the world point from the rig's arm transform (see `tipPt` in `video/dungeon`'s scene) so spells leave from the tip, not near it.
- Pigment mixing catches more than glows. A cream dust puff painted over Clawd turned purple, so draw effects that sit behind a character before `clawd()`.
