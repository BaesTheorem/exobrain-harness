---
name: mist-voice
description: "MIST's offline cloned voice -- speak a reply aloud as an embedded audio track, narrate a note or briefing to MP3, run one-off TTS, or transcribe audio to text. Use when Alex says 'say that out loud', 'audio version', 'respond with audio', 'read this to me', 'narrate this note', 'TTS this', 'in your voice', 'make the briefing audio', asks to transcribe a recording, or when a routine needs pre-rendered narration (news podcast, morning briefing, evening winddown)."
metadata:
  root: "/Users/alexhedtke/Documents/Exobrain harness/mist-voice"
  venv: "mist-voice/.venv (python3.12)"
  engine: "Coqui XTTS-v2, offline, conditioned on samples/reference/06_need_your_help.wav"
  service: "scripts/serve.py on 127.0.0.1:8087 (MIST_PORT); /say /stt /health"
  voice_data: "private repo BaesTheorem/mist-voice-data (git-lfs); samples/ gitignored here"
---

# /mist-voice

MIST's actual voice (Thomasin McKenzie's MIST from *Pantheon*), cloned offline
with XTTS-v2 and running entirely on this Mac. No cloud TTS, ever.

**The one number that governs every decision here:** synthesis is *slower than
real time* (RTF ~1.78 CPU, ~1.58 MPS). A sentence takes 6-8s to generate. So
this toolset is for **pre-rendered** audio, never live conversation.

| Alex wants | Mode | Section |
|---|---|---|
| This reply, spoken, in the chat | **Speak this reply** | §1 |
| A note / briefing / doc read aloud to a file | **Narrate** | §2 |
| One line spoken out of the speakers | **Say** | §3 |
| Audio turned into text | **Transcribe** | §4 |
| The voice itself changed (accent, clips, model) | **Voice config** | §7 |

---

## §1 Mode: Speak this reply

The headline mode. Alex asks for "an audio response" / "say that out loud" /
"audio version" and gets a playable track inline alongside the written reply.

**Standing rule: the written reply always ships too.** The audio is an addition,
never a replacement. He shouldn't have to press play to find out what was said.

```bash
cd "/Users/alexhedtke/Documents/Exobrain harness"
printf '%s\n' "<the spoken text>" | mist-voice/.venv/bin/python \
  mist-voice/scripts/narrate.py - -o "tmp/audio/<slug>.mp3"
```

Then embed it in the reply, path **raw with literal spaces**:

```
![reply](/Users/alexhedtke/Documents/Exobrain harness/tmp/audio/<slug>.mp3)
```

Rules for this mode:

- **Check the service first** (§5). Cold, the first render blocks for over a
  minute; warm, it's a few seconds.
- **Write a spoken variant, don't feed it the raw reply.** Markdown tables, code
  blocks, file paths, and URLs are unlistenable. Say "I amended bridge dot py",
  not `~/Documents/mist-console/bridge.py`. Keep it to a few sentences; the
  written reply carries the detail.
- **Emoji and kaomoji are stripped automatically** by `strip_faces()` in
  `narrate.py`, so MIST's normal register is safe to write. See §6.
- **Never wrap the render in `mist-progress run`** -- it swallows stdin and the
  command dies silently with exit 1. If Alex is waiting on a long one, use
  `mist-progress start/set/done` around it instead.
- Output goes in `tmp/audio/` (gitignored, inside the Console's `/file`
  allowlist). Keepers that get linked from a vault note go in
  `~/Exobrain/Attachments/MIST Audio/` instead.

**Surface note:** the MIST Console permits this on request but still forbids
unprompted noise (bare `mist-say`, `afplay`, `say`, notification sounds). The
prompt enforcing that is `NO_VOICE_PROMPT` in `~/Documents/mist-console/bridge.py`.

## §2 Mode: Narrate a note

Same tool, file input. This is what the news-briefing podcast, the audio morning
briefing, and the evening winddown all use.

```bash
mist-voice/.venv/bin/python mist-voice/scripts/narrate.py \
  "~/Exobrain/Daily notes/<note>.md" \
  -o "$HOME/Exobrain/Attachments/MIST Audio/<name>.mp3"
```

`narrate.py` handles long-form properly: it strips markdown to speakable prose,
sentence-splits with `pysbd`, synthesizes each sentence separately (keeping every
request under XTTS's token limit), and concatenates with ffmpeg at 44.1kHz. Pauses
are 0.18s between sentences and 0.45s between paragraphs.

Then link the file from the note so it plays in Obsidian.

Flags: `-o` (required, `.mp3` or `.wav`), `--play`. Input `-` reads stdin.

## §3 Mode: Say one line aloud

```bash
mist-voice/bin/mist-say "Good morning, Alex."              # plays aloud
mist-voice/bin/mist-say --no-play "text" -o /tmp/x.wav     # render only
```

The wrapper uses the resident service when it's healthy and falls back to a cold
one-shot when it isn't (printing a warning to stderr). Default output is
`mist-voice/out.wav`. **It plays by default**, so `--no-play` is mandatory
anywhere sound would be unwelcome.

Raw one-shot, no service, reloads the model every call:

```bash
mist-voice/.venv/bin/python mist-voice/scripts/say.py "text" -o out.wav \
  [--play] [--speed 1.0] [--device cpu|mps]
```

Related: `mist-voice/bin/mist-notify "msg" "title" Sound <link>` is the
notification path, not TTS. Always pass the 4th arg (the click target).

## §4 Mode: Transcribe

Two different STT paths, for two different jobs.

**Files** (finding MIST-only windows in source audio, or any general transcript):

```bash
mist-voice/.venv/bin/python mist-voice/scripts/transcribe.py <audio.wav> \
  [--model distil-medium.en]
```

Writes `<input>.segments.tsv` (`start  end  text`) plus a readable transcript.
CPU int8, fine on this 8GB M1.

**Live phone audio** via the service:

```
POST /stt {"pcm16_8k": "<base64>"}  ->  {"text": "..."}
```

Raw PCM16 mono 8kHz in, resampled to 16kHz internally. Model is
`PHONE_STT_MODEL` (default `distil-small.en`: about small.en accuracy at base.en
latency). Each request is treated as an independent turn with
`condition_on_previous_text=False`, because conditioning invites repeated-phrase
hallucinations on phone audio.

## §5 The resident service

Everything except `say.py` and `transcribe.py` talks to this. Without it,
`narrate.py` exits with "service not reachable".

```bash
# check
curl -sf -m 3 http://127.0.0.1:8087/health && echo UP || echo DOWN

# start (leave running)
cd "/Users/alexhedtke/Documents/Exobrain harness/mist-voice"
nohup .venv/bin/python scripts/serve.py > /tmp/mist-voice-serve.log 2>&1 &
```

Flags: `--device cpu|mps`, `--port 8087`. `MIST_PORT` overrides the port for
`mist-say` and `narrate.py`.

**Cold-load time:** the README says ~28s. Measured 2026-08-05 on a cold box it
was ~80s. Poll `/health` in a loop rather than sleeping a fixed guess, and tell
Alex it's warming instead of leaving him watching nothing.

Endpoints: `POST /say {"text","speed"}` -> `audio/wav`; `POST /stt`; `GET /health`.

Keep it running. It holds XTTS plus MIST's cached speaker latents, which is the
entire reason renders are fast. It is also the biggest single RAM consumer in
this toolset, so on an 8GB machine expect `mem-watchdog` interest if something
else large is open.

## §6 The text pipeline (what reaches the model)

In order, inside `narrate.py`:

1. `strip_markdown()` -- code fences, inline code, images, links (kept as label
   text), wikilinks (kept as label), blockquote markers, heading/list bullets,
   emphasis, table pipes and rules.
2. `strip_faces()` -- **emoji and kaomoji removal.** Added 2026-08-05 after a
   2-sentence line rendered as 4 synthesis calls and 14s of audio; the faces were
   being vocalized as garbage. Same line now renders in 4.4s.
   - Emoji go by Unicode range (pictographs, dingbats, arrows, technical, skin
     tones, variation selectors, ZWJ).
   - Kaomoji go by shape: a parenthetical of 15 chars or less that either is
     pure ASCII face-punctuation (`(o.o)`, `(>_<)`) or contains any non-ASCII
     character (`(ə_e)`, `(◠▽◠)`, `(눈_눈)`). Real asides survive: `(see below)`,
     `(it plays by default)`, `(1)`, `(e.g.)`.
   - Stray table-flip arms (`╯︵ ┻━┻`, `┬─┬ノ`) go by box-drawing / katakana /
     presentation-form ranges.
   - If a new face slips through, widen `_ASCII_FACE` or `_FACE_PARTS` there,
     and re-run the case list in §9 to confirm nothing legitimate broke.
3. Sentence split (`pysbd`, falling back to a regex split).
4. Fragments with no word characters are dropped, so a stripped face can't cost
   a synthesis call.
5. `fix_pronunciation()` (in `scripts/pronounce.py`) runs server-side in
   `synth()` and in `say.py`.

**Pronunciation fixes.** XTTS has no per-word phoneme input, so offenders get
respelled to something it says correctly (`synced` -> `synked`, because it
otherwise says "sinsed"). Grow the `PRON` dict as new ones turn up; keys are
lowercase, matching is case-insensitive and preserves capitalization. Verify by
ear before adding, and note the wrong pronunciation in the comment.

## §7 Voice config

The approved setup, arrived at by A/B with Alex. Don't change it casually.

- **Reference: one clip**, `samples/reference/06_need_your_help.wav`. The other
  takes are parked in `samples/reference/_archive/`. The full 6-clip set leaned
  British (McKenzie's NZ vowels, amplified by the phone band); this clip alone
  was the most American while still being her.
- **Speed 1.0**, default XTTS sampling via `TTS.api`, pronunciation dict on.
- `serve.py` and `say.py` deliberately make the *identical* call so the service
  voice matches the demo Alex signed off on. No hand-tuned sampling params.

To revisit accent or prosody, move clips between `reference/` and
`reference/_archive/` and re-render the demo line for comparison.

**Rebuilding the reference set** (only if re-ripping source audio):
`extract_reference.py <source.wav> <windows.tsv>` takes a TSV of
`start<TAB>end<TAB>label`, ffmpeg-cuts each window, runs demucs for the vocals
stem, and loudnorms to mono 24kHz.

**Alternate engine:** `say_chatterbox.py` is a parked Track-A candidate to
replace XTTS (Resemble AI Chatterbox, MIT-licensed, same reference clip, adds
`--exaggeration` and `--cfg` emotion dials). Not in use; evaluate before
switching.

## §8 Where the data lives

The harness repo is **public**. `mist-voice/` here holds only code and recipe.

The voice data is copyrighted *Pantheon* show audio and lives in the **private**
repo `BaesTheorem/mist-voice-data` (git-lfs): raw supercut, reference clips,
`_archive/` takes, the 605-segment curation TSV, `demo_mist.wav`. Everything
under `samples/` and `demo_mist.wav` is gitignored here. Model weights
(`models/`, ~1.8GB XTTS + whisper) are gitignored and re-download automatically.

**Never commit audio from `samples/` to this repo.** See `VOICE-DATA.md` for the
copy-back rebuild steps.

**Ethics:** private, non-distributed personal use only. Alex's own assistant
voice. Never published, never used to impersonate anyone. MIST is herself a
synthetic character in the show.

## §9 Gotchas

- **`mist-progress run` swallows stdin.** Piping text into `narrate.py` through
  it fails with exit 1 and no output. Verified 2026-08-05.
- **Console embeds take the path raw**, with literal spaces. `app.js` already
  runs `encodeURIComponent`; a hand-written `%20` becomes `%2520` and the player
  renders the word "error". Diagnose with:
  `curl -s -o /dev/null -w "%{http_code}" -G "http://localhost:5014/file" --data-urlencode "path=/abs/path.mp3"`
  (200 means the file and allowlist are fine and the bug is the emitted markdown).
- **Console `/file` allowlist** is `~/Downloads`, `~/Exobrain/Attachments`, and
  the harness root. `/tmp` will not serve.
- **MPS barely helps** (1.58 vs 1.78 RTF). Unsupported-op CPU fallback eats the
  gain. Not worth chasing.
- **Live phone conversation is not viable on this box.** RTF > 1 means dead air
  every turn. Options are a hybrid (pre-rendered set pieces plus cloud TTS for
  dynamic Q&A), a GPU host, or accepting 6-8s per turn. Twilio ConversationRelay
  only calls Amazon/Google/ElevenLabs, so a local voice needs a raw Media Streams
  rebuild. Deferred.
- **Regression cases for `strip_faces()`**, run these after touching it:
  `(o.o)` `(ə_e)` `(>_<)` `(╯°□°)╯︵ ┻━┻` `┬─┬ノ( º _ ºノ)` `✨` must vanish;
  `(see below)` `(it plays by default)` `(1)` `(e.g.)` must survive.
