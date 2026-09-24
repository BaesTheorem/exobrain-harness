"""Helpers that aren't the music model: a lyric writer and cover art.

Lyrics come from Claude through the `claude` CLI in print mode, with settings
disabled so no CLAUDE.md persona leaks into a song. Cover art comes from the
existing mist-image CLI (Cloudflare FLUX, about two seconds a picture).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from .config import HARNESS

MIST_IMAGE = os.path.join(HARNESS, "mist-image", "bin", "mist-image")

SECTION_TAGS = ["[Intro]", "[Verse 1]", "[Pre-Chorus]", "[Chorus]", "[Verse 2]", "[Bridge]",
                "[Outro]", "[Instrumental]", "[Hook]", "[Drop]"]


def find_claude() -> str | None:
    """The claude CLI, resolved at call time (never pinned: its install path moves).
    launchd's PATH is bare, so check the usual install dirs after PATH."""
    found = shutil.which("claude")
    if found:
        return found
    for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"):
        p = os.path.expanduser(os.path.join(d, "claude"))
        if os.access(p, os.X_OK):
            return p
    return None


def claude_available() -> bool:
    return find_claude() is not None


def write_lyrics(theme: str, style: str = "", language: str = "en", structure: str = "",
                 model: str = "claude-sonnet-5", timeout: int = 120) -> str:
    """Ask Claude for lyrics in the [Verse]/[Chorus] form ACE-Step expects."""
    exe = find_claude()
    if not exe:
        raise RuntimeError("The claude CLI isn't on PATH, so the lyric writer is unavailable.")
    lang = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
            "pt": "Portuguese", "ja": "Japanese", "ko": "Korean", "zh": "Mandarin Chinese"}.get(language, language)
    structure = structure or "Intro (2 lines), Verse 1, Chorus, Verse 2, Chorus, Bridge, Chorus, Outro"
    prompt = (
        "Write original song lyrics.\n"
        f"Theme: {theme.strip()}\n"
        f"Style: {style.strip() or 'unspecified'}\n"
        f"Language: {lang}\n"
        f"Structure: {structure}\n\n"
        "Rules: put each section under a bracketed tag on its own line, exactly like "
        "[Verse 1], [Chorus], [Bridge], [Outro]. Four to eight lines per section, one lyric line "
        "per line, no rhyme labels, no chords, no commentary, no title, no quotes. Singable "
        "lines under twelve syllables. Output only the tagged lyrics."
    )
    proc = subprocess.run([exe, "-p", prompt, "--setting-sources", "", "--model", model,
                           "--output-format", "text"], capture_output=True, text=True, timeout=timeout,
                          cwd=HARNESS)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or '')[-400:]}")
    text = proc.stdout.strip()
    # Keep from the first section tag on, in case a preamble slipped through.
    m = re.search(r"^\s*\[[^\]\n]+\]\s*$", text, re.M)
    if m:
        text = text[m.start():].strip()
    if not text:
        raise RuntimeError("Claude returned no lyrics.")
    return text


def suggest_caption(description: str, model: str = "claude-sonnet-5", timeout: int = 90) -> str:
    """One-sentence brief -> comma-separated ACE-Step style tags."""
    exe = find_claude()
    if not exe:
        raise RuntimeError("The claude CLI isn't on PATH.")
    prompt = (
        "Turn this song brief into a comma-separated list of 8 to 14 music style tags for a "
        "text-to-music model: genre, subgenre, mood, era, key instruments, vocal type, tempo in BPM, "
        "production feel. Lowercase, no sentences, no quotes, output only the list.\n\n"
        f"Brief: {description.strip()}"
    )
    proc = subprocess.run([exe, "-p", prompt, "--setting-sources", "", "--model", model,
                           "--output-format", "text"], capture_output=True, text=True, timeout=timeout,
                          cwd=HARNESS)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or '')[-400:]}")
    line = proc.stdout.strip().splitlines()
    return (line[-1] if line else "").strip().strip('"')


def art_prompt(meta: dict) -> str:
    caption = (meta.get("caption") or meta.get("description") or "music").strip()
    title = (meta.get("title") or "").strip()
    return (f"album cover art for a song titled '{title}', {caption}; bold graphic illustration, "
            "strong composition, no text, no letters, no watermark") if title else (
            f"album cover art, {caption}; bold graphic illustration, strong composition, no text")


def make_art(prompt: str, out_path: str, size: int = 768, timeout: int = 180) -> str:
    if not os.access(MIST_IMAGE, os.X_OK):
        raise RuntimeError("mist-image isn't available (mist-image/bin/mist-image).")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    proc = subprocess.run([MIST_IMAGE, prompt, "--size", str(size), "-o", out_path],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"mist-image failed: {(proc.stderr or proc.stdout)[-400:]}")
    return out_path
