#!/usr/bin/env python3
"""Battlefront reflexes for MIST: a fast loop that drives the ps5-session daemon.

Reads the live frame (player 1, top half of a horizontal split screen) about 8 times a
second through ``ps5ctl snap``, then:

- fires (holds R2) while the reticle is red, which the game shows over an enemy;
- turns toward the nearest red radar blip, or toward the red command post markers on the
  radar rim when no enemy is close, and walks forward;
- jumps and turns when the view stops changing while walking (stuck);
- taps X to respawn when the radar disappears (dead, on the spawn menus).

Control file ``<dir>/autopilot.json`` is re-read every loop: ``{"mode": "hunt"}``,
``{"mode": "pause"}`` (sticks centered, triggers released, no input), or
``{"mode": "hold"}`` (fire at targets and turn, but do not walk). Events go to
``<dir>/autopilot.log`` and a running summary to ``<dir>/autopilot.state.json``.
The HUD coordinates are for Star Wars Battlefront Classic Collection at 1280x720.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import socket
import time

import numpy as np
from PIL import Image

LIVE = pathlib.Path(__file__).resolve().parents[1] / "tmp" / "ps5-live"
HALF = 360  # player 1 owns rows 0..359
RETICLE_BOX = (slice(90, 230), slice(585, 695))
RADAR_C = (140, 245)
RADAR_R = 55
STICKY_FIRE = 0.8  # seconds
RETICLE_C = (640, 180)
CELL = 16  # blob grid cell, pixels
# screen zones that never hold a target: radar, ammo HUD, health HUD, PS5 toast, own body
MASK_ZONES = [(80, 180, 205, 310), (40, 40, 170, 105), (1105, 45, 1245, 125),
              (510, 10, 770, 70), (535, 195, 745, 360)]  # fmt: skip
AIM_GIVE_UP = 2.5  # seconds aiming at a blob without a red reticle
RIM_DIST = 42  # blips at or beyond this radius are pinned command post markers


def send(sock_path: pathlib.Path, line: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(10)
        s.connect(str(sock_path))
        s.sendall((line + "\n").encode())
        chunks = []
        while True:
            data = s.recv(65536)
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks).decode().strip()


class Pilot:
    def __init__(self, args: argparse.Namespace) -> None:
        self.dir = pathlib.Path(args.dir)
        self.sock = self.dir / "ctl.sock"
        # the daemon splits commands on whitespace, so the frame path must not contain spaces
        self.frame_path = pathlib.Path("/tmp/ps5-autopilot-frame.bmp")
        self.ctl_path = self.dir / "autopilot.json"
        self.log_path = self.dir / "autopilot.log"
        self.state_path = self.dir / "autopilot.state.json"
        self.hz = args.hz
        yy, xx = np.mgrid[0:HALF, 0:1280]
        self.disk = (xx - RADAR_C[0]) ** 2 + (yy - RADAR_C[1]) ** 2 <= RADAR_R**2
        self.firing = False
        self.alive = False
        self.dead_since: float | None = None
        self.last_x_tap = 0.0
        self.prev_small: np.ndarray | None = None
        self.still_since: float | None = None
        self.strafe_dir = 1.0
        self.strafe_flip_at = 0.0
        self.sweep_phase = random.random() * math.tau
        self.stats = {
            "started": time.strftime("%H:%M:%S"),
            "target_locks": 0,
            "fire_seconds": 0.0,
            "deaths": 0,
            "respawn_taps": 0,
            "stuck_escapes": 0,
            "mode": "hunt",
            "alive": False,
            "last_event": "",
        }
        self.on_target_since: float | None = None
        self.last_red = 0.0
        self.aim_since: float | None = None
        self.ignore_blobs_until = 0.0
        self.zone_mask = np.ones((HALF, 1280), dtype=bool)
        for x0, y0, x1, y1 in MASK_ZONES:
            self.zone_mask[y0:y1, x0:x1] = False
        self.zone_mask[:40] = False  # mountain rock along the top edge

    # --- io ------------------------------------------------------------------
    def log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.stats["last_event"] = line
        with self.log_path.open("a") as f:
            f.write(line + "\n")

    def mode(self) -> str:
        try:
            return json.loads(self.ctl_path.read_text()).get("mode", "hunt")
        except (OSError, ValueError):
            return "hunt"

    def frame(self) -> np.ndarray | None:
        reply = send(self.sock, f"snap {self.frame_path}")
        if not reply.startswith("ok"):
            return None
        return np.asarray(Image.open(self.frame_path).convert("RGB"))[:HALF].astype(
            np.int16
        )

    # --- perception ------------------------------------------------------------
    def perceive(self, a: np.ndarray) -> dict:
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        red = (r > 150) & (r - np.maximum(g, b) > 70)
        green = (g > 120) & (g - np.maximum(r, b) > 50)
        ys, xs = RETICLE_BOX
        ret_red = int(red[ys, xs].sum())
        ret_green = int(green[ys, xs].sum())
        disk_blue = int(((b > 150) & (b > r + 30) & self.disk).sum())
        blips = red & self.disk
        near = None
        rim = None
        if blips.any():
            py, px = np.nonzero(blips)
            ang = np.degrees(np.arctan2(px - RADAR_C[0], -(py - RADAR_C[1])))
            dist = np.hypot(px - RADAR_C[0], py - RADAR_C[1])
            inner = dist < RIM_DIST
            if inner.any():
                k = int(np.argmin(np.where(inner, dist, 1e9)))
                near = (float(ang[k]), float(dist[k]))
            outer = ~inner
            if outer.any():
                k = int(np.argmin(np.where(outer, np.abs(ang), 1e9)))
                rim = float(ang[k])
        blob = self.find_blob(r, g, b)
        top = a[:120]
        sky = (top[..., 2] > 150) & (top[..., 2] - top[..., 0] > 45)
        sky_frac = float(sky.mean())
        small = np.asarray(
            Image.fromarray(a.astype(np.uint8)).convert("L").resize((64, 18)),
            dtype=np.int16,
        )
        return {
            "target": ret_red > 120 and ret_green < 80,
            "friendly": ret_green > 120,
            "alive": disk_blue > 3000,
            "near": near,
            "rim": rim,
            "blob": blob,
            "sky": sky_frac,
            "small": small,
        }

    def find_blob(
        self, r: np.ndarray, g: np.ndarray, b: np.ndarray
    ) -> tuple[float, float] | None:
        """Return the (dx, dy) from the reticle to the nearest person-sized dark blob."""
        lum = (r * 3 + g * 6 + b) // 10
        dark = (lum < 105) & self.zone_mask
        h, w = HALF // CELL, 1280 // CELL
        cells = (
            dark[: h * CELL, : w * CELL].reshape(h, CELL, w, CELL).mean(axis=(1, 3))
            > 0.18
        )
        seen = np.zeros_like(cells)
        best = None
        for cy in range(h):
            for cx in range(w):
                if not cells[cy, cx] or seen[cy, cx]:
                    continue
                stack, members = [(cy, cx)], []
                seen[cy, cx] = True
                while stack:
                    y, x = stack.pop()
                    members.append((y, x))
                    for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                        if (
                            0 <= ny < h
                            and 0 <= nx < w
                            and cells[ny, nx]
                            and not seen[ny, nx]
                        ):
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                if not 1 <= len(members) <= 14:
                    continue  # too big: a walker, a bunker, a cliff
                ys = [m[0] for m in members]
                xs = [m[1] for m in members]
                if max(xs) - min(xs) > 4:
                    continue  # people are taller than wide
                if min(ys) * CELL < 60:
                    continue  # far mountains
                y0, y1 = min(ys) * CELL, (max(ys) + 1) * CELL
                x0, x1 = min(xs) * CELL, (max(xs) + 1) * CELL
                sel = dark[y0:y1, x0:x1]
                if sel.any():
                    mr = float(r[y0:y1, x0:x1][sel].mean())
                    mb = float(b[y0:y1, x0:x1][sel].mean())
                    if mb > mr + 12:
                        continue  # bluish: ice rock or shadow, not a Rebel
                bx = (sum(xs) / len(xs) + 0.5) * CELL
                by = (min(ys) + 0.6) * CELL  # aim high on the blob: chest, not feet
                dx, dy = bx - RETICLE_C[0], by - RETICLE_C[1]
                d = dx * dx + dy * dy
                if best is None or d < best[0]:
                    best = (d, dx, dy)
        return None if best is None else (best[1], best[2])

    # --- action ----------------------------------------------------------------
    def step(self) -> None:
        mode = self.mode()
        self.stats["mode"] = mode
        if mode == "pause":
            if self.firing:
                send(self.sock, "release R2")
                self.firing = False
            send(self.sock, "center")
            return
        a = self.frame()
        if a is None:
            return
        p = self.perceive(a)
        now = time.monotonic()
        cmds: list[str] = []

        # alive / dead
        if not p["alive"]:
            if self.alive:
                self.stats["deaths"] += 1
                self.log("radar gone: dead or in a menu")
            if self.dead_since is None:
                self.dead_since = now
            self.alive = False
            self.stats["alive"] = False
            if self.firing:
                cmds.append("release R2")
                self.firing = False
            cmds.append("center")
            dead_for = now - (self.dead_since or now)
            if 3.0 < dead_for < 90.0 and now - self.last_x_tap > 2.5:
                cmds.append("tap X")
                self.last_x_tap = now
                self.stats["respawn_taps"] += 1
            send(self.sock, "; ".join(cmds))
            return
        if not self.alive:
            self.log("radar back: alive")
            self.prev_small = None
        self.alive = True
        self.stats["alive"] = True
        self.dead_since = None

        # shooting: the reticle fades while the rifle fires, so keep the trigger down
        # for STICKY_FIRE seconds after the last red reading unless a friendly is in it
        if p["target"]:
            self.last_red = now
        engaged = p["target"] or (
            now - self.last_red < STICKY_FIRE and not p["friendly"]
        )
        if engaged and not self.firing:
            cmds.append("press R2")
            self.firing = True
            self.stats["target_locks"] += 1
            self.on_target_since = now
            self.log("target lock: firing")
        elif not engaged and self.firing:
            cmds.append("release R2")
            self.firing = False
            if self.on_target_since is not None:
                self.stats["fire_seconds"] += now - self.on_target_since
            self.on_target_since = None

        # strafe flip timer
        if now > self.strafe_flip_at:
            self.strafe_dir = -self.strafe_dir
            self.strafe_flip_at = now + random.uniform(0.8, 1.6)

        walk = mode != "hold"
        lx, ly, rx, ry = 0.0, 0.0, 0.0, 0.0
        if p["blob"] is None or engaged:
            self.aim_since = None
        if engaged:
            lx = 0.7 * self.strafe_dir  # dodge while shooting, keep the aim
        elif p["friendly"]:
            rx = 0.35  # look past a teammate
            ly = -0.6 if walk else 0.0
        elif p["blob"] is not None and now > self.ignore_blobs_until:
            dx, dy = p["blob"]
            self.aim_since = self.aim_since or now
            if now - self.aim_since > AIM_GIVE_UP:
                self.ignore_blobs_until = now + 3.0  # probably a rock or a droid
                self.aim_since = None
            rx = max(-1.0, min(1.0, dx / 220.0)) * 0.55
            ry = max(-1.0, min(1.0, dy / 110.0)) * 0.45
            ly = (-0.5 if abs(dx) > 260 else 0.0) if walk else 0.0
        elif p["near"] is not None:
            ang, dist = p["near"]
            rx = max(-1.0, min(1.0, ang / 45.0)) * 0.6
            ly = (-0.7 if dist > 18 else 0.0) if walk else 0.0
            lx = 0.4 * self.strafe_dir
        elif p["rim"] is not None:
            self.sweep_phase += 0.35
            rx = max(-1.0, min(1.0, p["rim"] / 60.0)) * 0.45 + 0.18 * math.sin(
                self.sweep_phase
            )
            ly = -1.0 if walk else 0.0
        else:
            self.sweep_phase += 0.35
            rx = 0.25 * math.sin(self.sweep_phase)
            ly = -1.0 if walk else 0.0

        # pitch leveling: too much blue sky means the camera drifted up
        if not engaged and (p["blob"] is None or now <= self.ignore_blobs_until):
            if p["sky"] > 0.12:
                ry = 0.35
        # stuck detection: walking but the view barely changes for 2.5 s
        if self.prev_small is not None and walk and ly < -0.5:
            diff = float(np.abs(p["small"] - self.prev_small).mean())
            if diff < 2.0:
                self.still_since = self.still_since or now
                if now - self.still_since > 2.5:
                    cmds.append("tap X")
                    rx = random.choice([-1.0, 1.0])
                    self.stats["stuck_escapes"] += 1
                    self.log("stuck: jump and turn")
                    self.still_since = None
            else:
                self.still_since = None
        self.prev_small = p["small"]

        cmds.append(f"stick left {lx:.2f} {ly:.2f}")
        cmds.append(f"stick right {rx:.2f} {ry:.2f}")
        send(self.sock, "; ".join(cmds))

    def run(self) -> None:
        self.log("autopilot start")
        period = 1.0 / self.hz
        last_state = 0.0
        try:
            while True:
                t0 = time.monotonic()
                try:
                    self.step()
                except (OSError, ConnectionError) as exc:
                    self.log(f"daemon unreachable: {exc}")
                    time.sleep(2)
                if t0 - last_state > 1.0:
                    self.state_path.write_text(json.dumps(self.stats, indent=1))
                    last_state = t0
                time.sleep(max(0.0, period - (time.monotonic() - t0)))
        finally:
            try:
                send(self.sock, "release R2; center")
            except OSError:
                pass
            self.log("autopilot stop")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--dir", default=str(LIVE))
    parser.add_argument("--hz", type=float, default=8.0)
    args = parser.parse_args()
    Pilot(args).run()


if __name__ == "__main__":
    main()
