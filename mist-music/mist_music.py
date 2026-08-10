#!/usr/bin/env python3
"""mist-music: MIST's music tool. Read sheet music, transcribe audio, generate.

Four subcommands, built so the heavy lifting either stays local (render,
transcribe) or runs on someone else's GPU (gen) so nothing melts the 8GB Air.

  # SHEET MUSIC IN -> audio out
  mist-music render score.mid                 # MIDI  -> mp3
  mist-music render sonata.musicxml -o s.mp3  # MusicXML/.mxl -> mp3
  mist-music render page.png                  # a PHOTO/scan of a score (OMR) -> mp3
  mist-music render score.pdf --wav           # PDF   -> wav

  # AUDIO CLIP IN -> notation out (so MIST can "read" what you play)
  mist-music transcribe riff.mp3              # audio -> riff.mid + riff.musicxml
  mist-music transcribe hum.wav --render      # ...and render the cleaned MIDI back to mp3

  # TEXT (+ lyrics, + optional melody) -> a FULL MP3 SONG, on a cloud GPU
  mist-music gen "dreamy synthwave, warm analog pads, 100 BPM, nostalgic" --duration 90
  mist-music gen "acoustic folk, fingerpicked guitar, soft female vocals" \
      --lyrics "[verse]\nMorning light on the kitchen floor\n[chorus]\n..."
  mist-music gen "cinematic orchestral, hopeful" --instrumental
  mist-music gen "lo-fi hip hop over this melody" --ref riff.wav        # condition on a clip
  mist-music gen "full band arrangement of this tune" --ref lead.musicxml # ...or sheet music

  mist-music play score.mid                   # render + open in the default player

Reliable core (render, transcribe) needs only fluidsynth + ffmpeg + the Basic
Pitch venv, all already installed. `gen` makes full songs (vocals + lyrics +
production) via ACE-Step on a free Hugging Face Space (gradio_client) -- no key
needed; HF_TOKEN is used if present. Songs save to tmp/audio/ so they embed and
play inline in the MIST Console with a download button.
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.dirname(HERE)
DEFAULT_DIR = os.path.abspath(os.path.join(HERE, "out"))
# Generated songs land here: tmp/audio under the harness root is gitignored and
# inside the MIST Console's /file allowlist, so they embed + play inline in chat.
AUDIO_EMBED_DIR = os.path.join(HARNESS, "tmp", "audio")
# harness .env lives one dir up from this script (mist-music/mist_music.py)
ENV_FILE = os.path.join(HERE, "..", ".env")

# Reuse the existing midi-tools installs rather than reinventing them.
MID2MP3 = os.path.expanduser("~/.local/bin/mid2mp3")
MP32MID = os.path.expanduser("~/.local/bin/mp32mid")

SHEET_IMG_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
MIDI_EXTS = {".mid", ".midi"}
SCORE_EXTS = {".xml", ".musicxml", ".mxl", ".abc", ".krn"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aiff", ".aif"}


def log(msg):
    print(f"[mist-music] {msg}", file=sys.stderr)


def die(msg, code=1):
    log(msg)
    sys.exit(code)


def load_env():
    """Pull KEY=VALUE lines from the harness .env into the environment.

    Existing real env vars win, so an inline override still works. Mirrors
    mist-image so one line in .env reaches scheduled calls too.
    """
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                line = line[len("export "):] if line.startswith("export ") else line
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


def ensure_out_path(inp, out, out_dir, default_ext):
    """Resolve the output path: explicit -o wins, else out_dir/<stem><ext>."""
    if out:
        return os.path.abspath(os.path.expanduser(out))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(inp))[0]
    return os.path.join(out_dir, stem + default_ext)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ---------------------------------------------------------------------------
# render: sheet music (MIDI / MusicXML / image / PDF) -> audio
# ---------------------------------------------------------------------------

def midi_to_audio(midi_path, out_path):
    """Render a MIDI file to mp3/wav via the existing mid2mp3 tool."""
    if not os.path.exists(MID2MP3):
        die(f"mid2mp3 not found at {MID2MP3} (part of the midi-tools install)")
    run([MID2MP3, midi_path, out_path])
    return out_path


def score_to_midi(score_path, tmpdir):
    """Parse a MusicXML/ABC/kern score with music21 and write a temp MIDI."""
    from music21 import converter
    log(f"parsing score with music21: {os.path.basename(score_path)}")
    s = converter.parse(score_path)
    midi_path = os.path.join(tmpdir, "score.mid")
    s.write("midi", fp=midi_path)
    return midi_path


def pdf_to_images(pdf_path, tmpdir):
    """Rasterize a PDF to page PNGs. Prefers pdftoppm, falls back to sips (page 1)."""
    from shutil import which
    if which("pdftoppm"):
        prefix = os.path.join(tmpdir, "page")
        run(["pdftoppm", "-png", "-r", "300", pdf_path, prefix])
        pages = sorted(
            os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
            if f.startswith("page") and f.endswith(".png")
        )
        return pages
    # macOS fallback: sips reads PDFs but only gives us the first page.
    log("pdftoppm not found (brew install poppler for multi-page); using sips on page 1")
    png = os.path.join(tmpdir, "page-1.png")
    run(["sips", "-s", "format", "png", pdf_path, "--out", png],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return [png]


def omr_to_musicxml(image_path, tmpdir):
    """Optical music recognition: score image -> MusicXML, via oemer."""
    try:
        import oemer  # noqa: F401
    except ImportError:
        die("OMR needs oemer. Install it: "
            "mist-music/.venv/bin/python -m pip install oemer")
    log(f"reading the score with OMR (oemer): {os.path.basename(image_path)} "
        "(first run downloads models, ~1-2 min)")
    # oemer writes <stem>.musicxml into -o's directory.
    run([os.path.join(HERE, ".venv", "bin", "oemer"), image_path, "-o", tmpdir])
    stem = os.path.splitext(os.path.basename(image_path))[0]
    xml = os.path.join(tmpdir, stem + ".musicxml")
    if not os.path.exists(xml):
        # oemer names vary by version; grab whatever .musicxml it produced.
        cands = [f for f in os.listdir(tmpdir) if f.endswith(".musicxml")]
        if not cands:
            die("OMR produced no MusicXML. The scan may be too low-contrast or skewed.")
        xml = os.path.join(tmpdir, cands[0])
    return xml


def cmd_render(args):
    inp = os.path.abspath(os.path.expanduser(args.input))
    if not os.path.exists(inp):
        die(f"no such file: {inp}")
    ext = os.path.splitext(inp)[1].lower()
    default_ext = ".wav" if args.wav else ".mp3"
    out_path = ensure_out_path(inp, args.output, args.dir, default_ext)

    with tempfile.TemporaryDirectory() as tmp:
        if ext in MIDI_EXTS:
            midi = inp
        elif ext in SCORE_EXTS:
            midi = score_to_midi(inp, tmp)
        elif ext in SHEET_IMG_EXTS:
            xml = omr_to_musicxml(inp, tmp)
            midi = score_to_midi(xml, tmp)
            if args.keep_xml:
                _stash_xml(xml, out_path)
        elif ext == ".pdf":
            pages = pdf_to_images(inp, tmp)
            from music21 import stream
            combined = stream.Score()
            for pg in pages:
                xml = omr_to_musicxml(pg, tmp)
                from music21 import converter
                combined.append(converter.parse(xml))
            midi = os.path.join(tmp, "score.mid")
            combined.write("midi", fp=midi)
        else:
            die(f"don't know how to render '{ext}'. Supported: MIDI, "
                "MusicXML/.mxl/.abc, score images (png/jpg/tif), or .pdf")
        midi_to_audio(midi, out_path)

    log(f"wrote {out_path}")
    print(out_path)
    if args.open:
        run(["open", out_path])


def _stash_xml(xml, out_path):
    import shutil
    dest = os.path.splitext(out_path)[0] + ".musicxml"
    shutil.copy(xml, dest)
    log(f"kept recognized notation: {dest}")


# ---------------------------------------------------------------------------
# transcribe: audio clip -> MIDI (+ MusicXML)
# ---------------------------------------------------------------------------

def cmd_transcribe(args):
    inp = os.path.abspath(os.path.expanduser(args.input))
    if not os.path.exists(inp):
        die(f"no such file: {inp}")
    if not os.path.exists(MP32MID):
        die(f"mp32mid not found at {MP32MID} (part of the midi-tools install)")

    midi_out = ensure_out_path(inp, args.output, args.dir, ".mid")
    log(f"transcribing audio with Basic Pitch: {os.path.basename(inp)}")
    run([MP32MID, inp, midi_out])
    print(midi_out)

    if not args.no_xml:
        try:
            from music21 import converter
            xml_out = os.path.splitext(midi_out)[0] + ".musicxml"
            converter.parse(midi_out).write("musicxml", fp=xml_out)
            log(f"wrote notation: {xml_out}")
            print(xml_out)
        except Exception as e:  # noqa: BLE001
            log(f"MIDI->MusicXML step failed ({e}); MIDI is still good.")

    if args.render:
        audio_out = os.path.splitext(midi_out)[0] + "-rendered.mp3"
        midi_to_audio(midi_out, audio_out)
        log(f"rendered cleaned take: {audio_out}")
        print(audio_out)


# ---------------------------------------------------------------------------
# gen: text (+ lyrics, + optional melody/reference) -> a full MP3 song.
#
# Backend: ACE-Step v1.5 running on a free public Hugging Face Space, driven via
# gradio_client. Full songs (vocals + lyrics + production), up to 240s, generated
# on their GPU so nothing touches this 8GB machine. No key needed for public
# Spaces; HF_TOKEN is used if present (higher quota / gated Spaces).
# ---------------------------------------------------------------------------

# ACE-Step's "prompt" field is really a comma-list of STYLE TAGS (genre, mood,
# instruments, BPM), and "lyrics" carries the words with [verse]/[chorus] tags.
#
# Two backends:
#   v15 (default) -- ACE-Step v1.5 "Studio" Space. Newer xl-turbo checkpoint,
#        a real `cover` task mode (source audio + cover-strength), faster/cleaner.
#        Its API is one big /generation_wrapper with ~49 positional params, so we
#        build the arg vector from the Space's live defaults and override by name.
#   v1  -- the original ACE-Step Space, simple /__call__. Kept as a fallback.
DEFAULT_SPACE = "ACE-Step/ACE-Step"          # v1 fallback
V15_SPACE = "ACE-Step/Ace-Step-v1.5"         # v1.5 Studio (preferred)


def _prep_reference(ref, tmpdir):
    """A reference for audio2audio can be an audio clip OR sheet music. If it's
    notation (MIDI/MusicXML/score image/PDF), render it to audio first so ACE-Step
    can condition on the melody. Returns a local audio filepath."""
    ext = os.path.splitext(ref)[1].lower()
    if ext in AUDIO_EXTS:
        return ref
    if ext in MIDI_EXTS:
        wav = os.path.join(tmpdir, "ref.wav")
        return midi_to_audio(ref, wav)
    if ext in SCORE_EXTS:
        return midi_to_audio(score_to_midi(ref, tmpdir), os.path.join(tmpdir, "ref.wav"))
    if ext in SHEET_IMG_EXTS:
        xml = omr_to_musicxml(ref, tmpdir)
        return midi_to_audio(score_to_midi(xml, tmpdir), os.path.join(tmpdir, "ref.wav"))
    die(f"can't use '{ext}' as a reference. Give an audio clip or sheet music.")


def _extract_audio(result):
    """Pull the first real audio filepath out of a Space's return."""
    if isinstance(result, (list, tuple)):
        for item in result:
            got = _extract_audio(item)
            if got:
                return got
        return None
    audio = result
    if isinstance(audio, dict):
        audio = audio.get("path") or audio.get("value") or audio.get("name")
    if audio and isinstance(audio, str) and os.path.exists(audio):
        return audio
    return None


def _gen_v1(client, args, ref_path, lyrics, handle_file):
    """Original ACE-Step Space: one flat /__call__."""
    return client.predict(
        float(args.duration),      # audio_duration (-1 = auto)
        args.prompt,               # prompt = style tags
        lyrics,                    # lyrics
        int(args.steps),           # infer_step
        15.0, "euler", "apg", 10.0,
        args.seed or None,         # manual_seeds
        0.5, 0.0, 3.0,
        True, False, True,         # use_erg_tag/lyric/diffusion
        None, 0.0, 0.0,
        bool(ref_path),            # audio2audio_enable
        float(args.ref_strength),  # ref_audio_strength
        handle_file(ref_path) if ref_path else None,  # ref_audio_input
        "none",                    # lora
        api_name="/__call__",
    )


def _gen_v15(client, args, ref_path, lyrics, handle_file):
    """ACE-Step v1.5 Studio Space. Build the /generation_wrapper arg vector from
    the Space's own live defaults, then override the slots we drive by parameter
    name -- resilient if the Space reorders/adds params. Cover mode feeds the
    source track through param_17 + precomputed audio codes (/lambda_4)."""
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):  # view_api prints a summary
            api = client.view_api(return_format="dict")
        params = api["named_endpoints"]["/generation_wrapper"]["parameters"]
    except Exception as e:  # noqa: BLE001
        die(f"couldn't read the v1.5 Space API: {e}")

    vec = [p.get("parameter_default") for p in params]
    idx = {p.get("parameter_name"): i for i, p in enumerate(params)}

    def put(name, value):
        if name in idx:
            vec[idx[name]] = value

    cover = bool(ref_path)
    # DiT steps: xl-turbo wants few steps (slider is 1..20); clamp our --steps.
    steps = min(max(int(args.steps), 1), 20)

    put("selected_model", "acestep-v15-xl-turbo")
    put("generation_mode", "cover" if cover else "custom")
    put("simple_query_input", args.prompt)     # required even in custom/cover mode
    put("param_4", args.prompt)                 # Prompt (style tags)
    put("param_5", lyrics)                      # Lyrics ([inst] for instrumental)
    put("param_10", steps)                      # DiT Inference Steps
    put("param_12", not args.seed)              # Random Seed (checkbox)
    put("param_13", str(args.seed) if args.seed else "-1")
    put("param_14", None)                       # Reference Audio (unused; cover uses Source)
    put("param_15", -1.0 if cover else float(args.duration))  # cover matches source length
    put("param_16", 1)                          # batch size -> one sample (saves GPU/quota)
    put("param_23", "cover" if cover else "text2music")  # task type
    put("param_22", float(args.ref_strength))   # cover strength (0..1)
    put("param_30", "mp3")                       # Audio Format
    put("param_47", "strings")                   # required instrument literal (no-op w/ empty list)
    put("param_48", [])

    if cover:
        src = handle_file(ref_path)
        put("param_17", src)                     # Source Audio
        log("encoding the reference track (cover mode) ...")
        try:
            codes = client.predict(src, api_name="/lambda_4")
        except Exception as e:  # noqa: BLE001
            die(f"couldn't encode the reference audio for cover mode: {e}")
        put("param_18", codes if isinstance(codes, str) else "")

    return client.predict(*vec, api_name="/generation_wrapper")


def cmd_gen(args):
    try:
        from gradio_client import Client, handle_file
    except ImportError:
        die("gen needs gradio_client: "
            "mist-music/.venv/bin/python -m pip install gradio_client")

    lyrics = args.lyrics
    if args.lyrics_file:
        with open(os.path.expanduser(args.lyrics_file)) as f:
            lyrics = f.read()
    if args.instrumental or not lyrics:
        lyrics = "[inst]"

    backend = args.backend
    if backend == "auto":
        # v1.5 unless the user pointed --space at the old one explicitly.
        backend = "v1" if (args.space and "Ace-Step-v1.5" not in args.space
                           and args.space != V15_SPACE) else "v15"
    default_space = V15_SPACE if backend == "v15" else DEFAULT_SPACE
    space = args.space or os.environ.get("MIST_MUSIC_SPACE") or default_space
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

    out_path = ensure_out_path("song", args.output, args.dir, ".mp3")

    with tempfile.TemporaryDirectory() as tmp:
        ref_path = _prep_reference(os.path.expanduser(args.ref), tmp) if args.ref else None

        log(f"connecting to {space} ({backend}) ...")
        try:
            client = Client(space, verbose=False, token=hf_token)
        except Exception as e:  # noqa: BLE001
            die(f"couldn't reach the generation Space ({space}): {e}\n"
                "Free Spaces sleep or queue. Retry in a moment, or pass --space "
                "with another ACE-Step Space.")

        kind = "cover" if ref_path else ("a full song" if lyrics != "[inst]" else "an instrumental")
        log(f"generating {kind} on {backend} ...")
        try:
            gen = _gen_v15 if backend == "v15" else _gen_v1
            result = gen(client, args, ref_path, lyrics, handle_file)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            die(f"generation failed: {e}\n"
                "The free Space may be busy, out of ZeroGPU quota, or updated its "
                "API. Retry, pass --space with another ACE-Step Space, or "
                "--backend v1 for the old engine.")

    audio = _extract_audio(result)
    if not audio:
        die(f"the Space returned no audio file (got: {result!r}).")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    import shutil
    shutil.copy2(audio, out_path)
    log(f"wrote {out_path}")
    print(out_path)

    # Emit a markdown image-embed pointing at the mp3. The MIST Console renders
    # local-audio paths as an inline <audio> player with a Save-to-Downloads
    # button (same chrome as generated images). Harmless plain text elsewhere.
    if not args.no_embed:
        title = (args.prompt or "song").strip().split(",")[0][:60]
        print(f"\n![{title}]({out_path})")
    if args.open:
        run(["open", out_path])


# ---------------------------------------------------------------------------
# sfx: text -> a sound effect (NOT music)
#
# Different problem from `gen`. ACE-Step is a *music* model: it wants to give
# you stable pitch, meter and harmony, which is exactly wrong for a creature
# snarl or a door creak. These models are trained on recorded environmental
# audio instead, so they produce aperiodic, noisy, non-tonal material by
# default -- the thing oscillator-based synthesis structurally can't fake.
#
# Backends verified live 2026-07-27 (probe of 9 candidates; audioldm2, tango
# and stable-audio-open-1.0 were all down/404, so they're deliberately absent):
#   audiogen    - Meta AudioGen. Purpose-built for sound effects. Best raw
#                 SFX character, but SHORT (the Space caps out around 10s).
#   stableaudio - Stable Audio Open. Long-form (up to 47s) foley, the only one
#                 that covers a full 20s+ cue in one pass.
#   tangoflux   - fast, clean, good on layered/complex prompts.
#   mmaudio     - the only one with a seed (reproducible) and a negative prompt
#                 (useful for steering AWAY from music: "music, melody, tonal").
# ---------------------------------------------------------------------------

SFX_BACKENDS = {
    "audiogen":    {"space": "fffiloni/AudioGen",                  "ep": "/infer",           "max": 10.0},
    "stableaudio": {"space": "artificialguybr/Stable-Audio-Open-Zero", "ep": "/predict",     "max": 47.0},
    "tangoflux":   {"space": "declare-lab/TangoFlux",              "ep": "/predict",         "max": 30.0},
    "mmaudio":     {"space": "hkchengrex/MMAudio",                 "ep": "/text_to_audio",   "max": 10.0},
}

# These models drift toward music if you let them. Pushing back explicitly
# helps on the two backends that accept a negative prompt.
SFX_NEGATIVE = "music, melody, singing, rhythm, drums, musical instruments, tonal, harmony"


def _sfx_args(backend, prompt, dur, args):
    """Build the positional arg vector for one backend's endpoint.

    GOTCHA (verified 2026-07-27): stableaudio and tangoflux DECLARE steps and
    duration as `float` in their gradio schema, but their server code does
    `range(steps)` on it -- so a float raises a bare `AppError: TypeError` with
    no message. Trust the traceback, not the published schema: send ints.
    Guidance/cfg is genuinely a float and is fine either way.
    """
    if backend == "audiogen":
        return [prompt, float(dur)]
    if backend == "stableaudio":
        return [prompt, int(dur), int(args.steps), float(args.cfg)]
    if backend == "tangoflux":
        return [prompt, int(args.steps), float(args.cfg), int(dur)]
    if backend == "mmaudio":
        neg = args.negative if args.negative is not None else SFX_NEGATIVE
        seed = int(args.seed) if args.seed else -1
        return [prompt, neg, seed, int(args.steps), float(args.cfg), float(dur)]
    die(f"unknown sfx backend {backend}")


def cmd_sfx(args):
    try:
        from gradio_client import Client
    except ImportError:
        die("sfx needs gradio_client: "
            "mist-music/.venv/bin/python -m pip install gradio_client")

    backend = args.backend
    spec = SFX_BACKENDS[backend]
    space = args.space or spec["space"]
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

    dur = float(args.duration)
    if dur > spec["max"]:
        log(f"note: {backend} caps at {spec['max']:g}s; asking for {spec['max']:g} "
            f"(use --takes to build a longer cue, or --backend stableaudio for up to 47s)")
        dur = spec["max"]

    log(f"connecting to {space} ({backend}) ...")
    try:
        client = Client(space, verbose=False, token=hf_token)
    except Exception as e:  # noqa: BLE001
        die(f"couldn't reach the SFX Space ({space}): {e}\n"
            "Free Spaces sleep, queue, or hit ZeroGPU quota. Retry, or pass "
            "--backend with another engine (see --help).")

    takes = []
    for i in range(max(1, int(args.takes))):
        label = f"take {i + 1}/{args.takes}" if args.takes > 1 else "sound"
        log(f"generating {label} on {backend} ({dur:g}s) ...")
        try:
            result = client.predict(*_sfx_args(backend, args.prompt, dur, args),
                                    api_name=spec["ep"])
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            die(f"generation failed: {e}\n"
                "The free Space may be busy or out of ZeroGPU quota. Retry, or "
                "try --backend audiogen / stableaudio / tangoflux / mmaudio.")
        got = _extract_audio(result)
        if not got:
            die(f"the Space returned no audio file (got: {result!r}).")
        takes.append(got)

    stem = args.output or None
    out_path = ensure_out_path(f"sfx-{backend}", stem, args.dir, ".mp3")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if len(takes) == 1:
        _to_mp3(takes[0], out_path)
    else:
        _concat_audio(takes, out_path, crossfade=args.crossfade)

    log(f"wrote {out_path}")
    print(out_path)
    if not args.no_embed:
        title = (args.prompt or "sfx").strip().split(",")[0][:60]
        print(f"\n![{title}]({out_path})")
    if args.open:
        run(["open", out_path])


def _to_mp3(src, dst):
    """Spaces hand back wav/flac; the Console plays either, but mp3 keeps the
    embed small and matches what `gen` writes."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-codec:a", "libmp3lame", "-b:a", "320k", dst])
    return dst


def _concat_audio(paths, dst, crossfade=0.0):
    """Stitch takes into one longer cue. These models are short-form, so a long
    creature cue is several takes butted together; a crossfade hides the seams."""
    if crossfade and len(paths) > 1:
        # chain acrossfade pairwise: ((a x b) x c) ...
        inputs, filt, prev = [], [], None
        for p in paths:
            inputs += ["-i", p]
        for i in range(1, len(paths)):
            a = prev or "[0:a]"
            out = f"[x{i}]"
            filt.append(f"{a}[{i}:a]acrossfade=d={crossfade}:c1=tri:c2=tri{out}")
            prev = out
        run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
             "-filter_complex", ";".join(filt), "-map", prev,
             "-codec:a", "libmp3lame", "-b:a", "320k", dst])
    else:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for p in paths:
                f.write(f"file '{os.path.abspath(p)}'\n")
            lst = f.name
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-codec:a", "libmp3lame", "-b:a", "320k", dst])
        os.unlink(lst)
    return dst


# ---------------------------------------------------------------------------
# play: render + open
# ---------------------------------------------------------------------------

def cmd_play(args):
    args.open = True
    cmd_render(args)


def build_parser():
    p = argparse.ArgumentParser(
        prog="mist-music",
        description="MIST's music tool: render sheet music, transcribe audio, generate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("-o", "--output", help="output file (default out/<name>.<ext>)")
        sp.add_argument("--dir", default=DEFAULT_DIR, help=f"output dir (default {DEFAULT_DIR})")

    r = sub.add_parser("render", help="sheet music (MIDI/MusicXML/image/PDF) -> audio")
    r.add_argument("input")
    add_common(r)
    r.add_argument("--wav", action="store_true", help="output WAV instead of MP3")
    r.add_argument("--keep-xml", action="store_true", help="save recognized notation (OMR only)")
    r.add_argument("--open", action="store_true", help="open the result when done")
    r.set_defaults(func=cmd_render)

    t = sub.add_parser("transcribe", help="audio clip -> MIDI + MusicXML")
    t.add_argument("input")
    add_common(t)
    t.add_argument("--no-xml", action="store_true", help="skip the MusicXML step")
    t.add_argument("--render", action="store_true", help="also render the cleaned MIDI to mp3")
    t.set_defaults(func=cmd_transcribe)

    g = sub.add_parser("gen", help="text (+ lyrics, + optional melody) -> a full MP3 song")
    g.add_argument("prompt", help="style tags: genre, mood, instruments, BPM "
                   "(e.g. 'dreamy synthwave, warm pads, 100 BPM, nostalgic')")
    g.add_argument("-o", "--output", help="output file (default tmp/audio/song.mp3)")
    g.add_argument("--dir", default=AUDIO_EMBED_DIR,
                   help=f"output dir (default {AUDIO_EMBED_DIR}; kept in the Console-servable temp dir)")
    g.add_argument("--lyrics", help="song lyrics, use [verse]/[chorus]/[bridge] tags")
    g.add_argument("--lyrics-file", help="read lyrics from a file")
    g.add_argument("--instrumental", action="store_true", help="no vocals")
    g.add_argument("--duration", type=int, default=60, help="seconds, up to 240 (-1 = auto)")
    g.add_argument("--ref", help="condition on a melody: an audio clip OR sheet music "
                   "(MIDI/MusicXML/score image/PDF, rendered to audio first)")
    g.add_argument("--ref-strength", type=float, default=0.5, help="0..1 how much the ref steers it")
    g.add_argument("--steps", type=int, default=60, help="inference steps (quality vs speed)")
    g.add_argument("--seed", help="manual seed(s) for reproducibility")
    g.add_argument("--backend", choices=["auto", "v15", "v1"], default="auto",
                   help="engine: v15 = ACE-Step 1.5 Studio w/ cover mode (default), "
                        "v1 = original Space (auto picks v15)")
    g.add_argument("--space", help=f"HF Space to use (default {V15_SPACE} for v15)")
    g.add_argument("--no-embed", action="store_true", help="don't print the Console audio-embed line")
    g.add_argument("--open", action="store_true", help="open the result when done")
    g.set_defaults(func=cmd_gen)

    s = sub.add_parser("sfx", help="text -> a sound effect (creature, foley, ambience -- NOT music)")
    s.add_argument("prompt", help="describe the SOUND, not a genre "
                   "(e.g. 'huge reptile snarling and gurgling, wet throat clicks, low breath')")
    s.add_argument("-o", "--output", help="output file (default tmp/audio/sfx-<backend>.mp3)")
    s.add_argument("--dir", default=AUDIO_EMBED_DIR,
                   help=f"output dir (default {AUDIO_EMBED_DIR}; Console-servable)")
    s.add_argument("--backend", choices=sorted(SFX_BACKENDS), default="stableaudio",
                   help="audiogen = best SFX character but <=10s; stableaudio = up to 47s "
                        "(default); tangoflux = fast/clean; mmaudio = seeded + negative prompt")
    s.add_argument("--duration", type=float, default=10.0, help="seconds (clamped per backend)")
    s.add_argument("--takes", type=int, default=1,
                   help="generate N takes and stitch them into one longer cue")
    s.add_argument("--crossfade", type=float, default=0.0,
                   help="seconds of crossfade between takes (hides the seams)")
    s.add_argument("--steps", type=int, default=100, help="inference steps (quality vs speed)")
    s.add_argument("--cfg", type=float, default=7.0, help="guidance: how literally it follows the prompt")
    s.add_argument("--seed", help="seed for reproducibility (mmaudio only)")
    s.add_argument("--negative", help="what to steer AWAY from (mmaudio only; "
                                      "defaults to anti-music terms)")
    s.add_argument("--space", help="override the HF Space")
    s.add_argument("--no-embed", action="store_true", help="don't print the Console audio-embed line")
    s.add_argument("--open", action="store_true", help="open the result when done")
    s.set_defaults(func=cmd_sfx)

    pl = sub.add_parser("play", help="render sheet music and open it")
    pl.add_argument("input")
    add_common(pl)
    pl.add_argument("--wav", action="store_true")
    pl.add_argument("--keep-xml", action="store_true")
    pl.set_defaults(func=cmd_play, open=True)

    return p


def main():
    load_env()
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
