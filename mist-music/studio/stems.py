"""Stem separation: vocals / instrumental (or four stems) out of any track.

Local first: demucs (htdemucs) is installed as a uv tool and, measured
2026-09-23 on the 8 GB Air, separates a 30 s clip in ~14 s at a 1.8 GB peak,
so a full song is a minute or two and stays well under the memory watchdog.
`--segment 7` is required: htdemucs is a transformer trained for 7.8 s windows
and refuses longer segments.

Cloud fallback: r3gm/Audio_separator on Hugging Face (ZeroGPU, so it draws on
the same daily quota as generation; use it only when local can't run).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Callable

DEMUCS = shutil.which("demucs") or os.path.expanduser("~/.local/bin/demucs")
CLOUD_SPACE = "r3gm/Audio_separator"


def local_available() -> bool:
    return os.access(DEMUCS, os.X_OK)


def separate_local(audio_path: str, out_dir: str, mode: str = "two",
                   progress: Callable[[dict], None] | None = None) -> dict[str, str]:
    """Run demucs; returns {stem: path}. mode = two (vocals + no_vocals) | four."""
    if not local_available():
        raise RuntimeError("demucs is not installed (uv tool install demucs).")
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [DEMUCS, "-d", "cpu", "--segment", "7", "--mp3", "--mp3-bitrate", "192", "-o", tmp]
        if mode == "two":
            cmd += ["--two-stems", "vocals"]
        cmd.append(audio_path)
        if progress:
            progress({"stage": "running", "detail": f"demucs {mode}-stem"})
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=3600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-800:]
            raise RuntimeError(f"demucs failed (exit {proc.returncode}): {tail}")
        model_dir = os.path.join(tmp, "htdemucs")
        track = os.path.splitext(os.path.basename(audio_path))[0]
        src_dir = os.path.join(model_dir, track)
        if not os.path.isdir(src_dir):
            # demucs names the folder after the track stem; find whatever it made
            subs = [os.path.join(model_dir, d) for d in os.listdir(model_dir)] if os.path.isdir(model_dir) else []
            subs = [d for d in subs if os.path.isdir(d)]
            if not subs:
                raise RuntimeError("demucs produced no output folder")
            src_dir = subs[0]
        out = {}
        for f in os.listdir(src_dir):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in (".mp3", ".wav"):
                continue
            name = "instrumental" if stem == "no_vocals" else stem
            dst = os.path.join(out_dir, name + ext.lower())
            shutil.move(os.path.join(src_dir, f), dst)
            out[name] = dst
    return out


def separate_cloud(audio_path: str, out_dir: str, token: str | None,
                   progress: Callable[[dict], None] | None = None) -> dict[str, str]:
    """Two stems (vocal + background) from the r3gm Space."""
    from gradio_client import Client, handle_file
    os.makedirs(out_dir, exist_ok=True)
    if progress:
        progress({"stage": "queued", "detail": f"cloud separator {CLOUD_SPACE}"})
    client = Client(CLOUD_SPACE, verbose=False, token=token)
    files = client.predict(handle_file(audio_path), ["vocal", "background"], False, False, False, False,
                           0.15, 0.7, 0.8, 0.2, 0.0, 0.0, -15, 4.0, 1.0, 100, 0, 120, 11000, 0.1, 0.5,
                           0.25, -15, 4.0, 15, 60, 0, "MP3", api_name="/sound_separate")
    out = {}
    for i, item in enumerate(files or []):
        p = item.get("path") if isinstance(item, dict) else item
        if not (isinstance(p, str) and os.path.isfile(p)):
            continue
        low = os.path.basename(p).lower()
        name = "vocals" if "vocal" in low else "instrumental" if ("background" in low or "instr" in low) \
            else f"stem{i + 1}"
        dst = os.path.join(out_dir, name + os.path.splitext(p)[1].lower())
        shutil.copy2(p, dst)
        out[name] = dst
    if not out:
        raise RuntimeError("The separator Space returned no files.")
    return out


def separate(audio_path: str, out_dir: str, mode: str = "two", engine: str = "local",
             token: str | None = None, progress: Callable[[dict], None] | None = None) -> dict[str, str]:
    if engine == "cloud" or (engine == "auto" and not local_available()):
        return separate_cloud(audio_path, out_dir, token, progress)
    return separate_local(audio_path, out_dir, mode, progress)
