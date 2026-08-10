"""!ace -- render the recent conversation as an Ace Attorney courtroom video.

Fletcher's swag.py has an `!ace` generator; this is the real "Ace Attorney video
generator." It dramatizes the last few messages as a Phoenix-Wright-style scene
(character sprites, text boxes, music) with the `objection_engine` library, which
pins old, heavy deps that can't share the bot's main venv. So it runs in a
dedicated `.ace-venv` (see README) invoked as a subprocess, off the gateway loop.

Because each render is a heavy CPU+ffmpeg load on Alex's personal machine, it is
guarded hard:
  * **one render at a time** (an asyncio.Lock; concurrent calls are turned away);
  * **a global throttle** -- more than 5 renders in 10 minutes trips a 30-minute
    lockout for everyone, so the command can't be weaponized to spam-load the box.

Disabled gracefully if the `.ace-venv` isn't built.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

import discord

from handler import Context

log = logging.getLogger("fletcher")

HERE = Path(__file__).resolve().parent.parent  # claude-bot/
ACE_PY = HERE / ".ace-venv" / "bin" / "python"
ACE_SCRIPT = HERE / "ace_render.py"
# objection_engine downloads its sprite/music pack into ./assets RELATIVE TO THE
# WORKING DIR, so we always render from this one stable, gitignored cache dir.
# That downloads the ~100MB pack exactly once instead of per-render.
ACE_CACHE = HERE / ".ace-cache"

RENDER_TIMEOUT = 300            # kill a render after 5 min
MAX_UPLOAD = 24 * 1024 * 1024   # stay under Discord's base 25MB limit
DEFAULT_MSGS = 6
MAX_MSGS = 12


class AceLimiter:
    """Global render throttle protecting the host. At most MAX_PER_WINDOW renders
    per WINDOW seconds; exceeding that engages a PENALTY-second lockout."""

    WINDOW = 600            # 10 minutes
    MAX_PER_WINDOW = 5
    PENALTY = 1800          # 30 minutes

    def __init__(self) -> None:
        self._starts: list[float] = []
        self._penalty_until = 0.0

    def blocked_for(self) -> float:
        """Seconds the command is blocked for, or 0.0 if a render may proceed.
        Tripping the per-window cap engages the penalty as a side effect."""
        now = time.monotonic()
        if now < self._penalty_until:
            return self._penalty_until - now
        self._starts = [t for t in self._starts if now - t < self.WINDOW]
        if len(self._starts) >= self.MAX_PER_WINDOW:
            self._penalty_until = now + self.PENALTY
            return self.PENALTY
        return 0.0

    def record(self) -> None:
        self._starts.append(time.monotonic())


def _fmt_duration(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m and s:
        return f"{m}m{s}s"
    return f"{m}m" if m else f"{s}s"


def setup(ctx: Context) -> None:
    if not ACE_PY.exists() or not ACE_SCRIPT.exists():
        log.info("ace module disabled -- .ace-venv not built (see README 'Ace Attorney')")
        return
    ACE_CACHE.mkdir(exist_ok=True)  # objection_engine caches its asset pack here

    h = ctx.handler
    q = ctx.quips
    prefix = ctx.config.prefix
    limiter = AceLimiter()
    render_lock = asyncio.Lock()  # one render at a time

    q.add("ace", ["Take that! 🫡", "No further questions 👀",
                  "The defense rests ✨", "Objection sustained ^_^"])

    # moviepy/ffmpeg need a real PATH; launchd gives a minimal one.
    _env = dict(os.environ)
    _env["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin", _env.get("PATH", "")])

    async def _render(scene: list[dict]) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="ace_"))
        scene_path = tmp / "scene.json"
        out_path = tmp / "objection.mp4"
        scene_path.write_text(json.dumps(scene))
        proc = await asyncio.create_subprocess_exec(
            str(ACE_PY), str(ACE_SCRIPT), str(scene_path), str(out_path),
            cwd=str(ACE_CACHE), env=_env,  # render from the cached-assets dir
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=RENDER_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError("render timed out") from None
        if proc.returncode != 0 or not out_path.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"render failed ({proc.returncode}): {err.decode()[-300:]}")
        return out_path

    @h.command("!ace", "!objection",
               description="Turn the last few messages into an Ace Attorney video (`!ace [count]`)",
               cooldown=10.0)
    async def ace_cmd(message: discord.Message, args: list[str], ctx: Context):  # noqa: ARG001
        # --- guard 1: one render at a time ---
        if render_lock.locked():
            await message.reply("I'm already rendering one, hold on ^_^", mention_author=False)
            return
        # --- guard 2: global throttle (protects the host from render-spam) ---
        blocked = limiter.blocked_for()
        if blocked:
            await message.reply(
                f"The courtroom's overbooked. Try again in {_fmt_duration(blocked)}. "
                f"(Max 5 renders per 10 min so nobody melts my machine. 🫡)",
                mention_author=False)
            return

        n = DEFAULT_MSGS
        if args and args[0].isdigit():
            n = min(max(int(args[0]), 2), MAX_MSGS)

        scene: list[dict] = []
        async for m in message.channel.history(limit=n + 8):
            if m.id == message.id or m.author.bot:
                continue
            text = (m.clean_content or "").strip()
            if not text or text.startswith(prefix):
                continue
            scene.append({"name": m.author.display_name, "text": text[:255]})
            if len(scene) >= n:
                break
        scene.reverse()
        if len(scene) < 2:
            await message.reply(
                "I need at least a couple of recent messages to put on trial. ⚖️",
                mention_author=False)
            return

        limiter.record()
        async with render_lock:
            try:
                await message.add_reaction("⚖️")
            except discord.HTTPException:
                pass
            note = await message.reply("Rendering the courtroom, this takes a minute... ⚖️",
                                       mention_author=False)
            out = None
            try:
                async with message.channel.typing():
                    out = await _render(scene)
                if out.stat().st_size > MAX_UPLOAD:
                    await note.edit(content="That scene rendered too big to upload. Try fewer messages, like `!ace 4`. >_<")
                    return
                await message.reply(
                    content=q.tag("⚖️ Order! Order in the court!", "ace"),
                    file=discord.File(str(out), filename="objection.mp4"),
                    mention_author=False)
                await note.delete()
            except Exception:
                log.exception("ace render failed")
                try:
                    await note.edit(content="The render fell apart on me. >_< Try again in a bit.")
                except discord.HTTPException:
                    pass
            finally:
                if out is not None:
                    shutil.rmtree(out.parent, ignore_errors=True)

    log.info("ace ready -- Ace Attorney video generator (1 at a time, 5/10min then 30min lockout)")
