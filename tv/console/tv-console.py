#!/usr/bin/env python3
"""
TV Console -- full-screen TUI for controlling the Samsung TV.
Hotkey-driven. Live status. App launcher grid. Recent command log.
"""

import sys
import time
import json
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tv_control as t

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Grid
from textual.widgets import Static, Footer, Input, Log
from textual.binding import Binding
from textual.reactive import reactive


CSS = """
Screen {
    background: $surface;
    color: $text;
    layout: vertical;
}

#status-panel {
    height: 5;
    border: round $primary;
    padding: 0 1;
    background: $panel;
}
#tv-name {
    text-style: bold;
    color: $accent;
}
#status-line { color: $text; }
#status-line.off { color: $error; }

#hotkeys-panel {
    height: 4;
    border: round $secondary;
    padding: 0 1;
}
#hotkeys { color: $text-muted; }

#apps-panel {
    height: 10;
    border: round $secondary;
    padding: 0 1;
}
#apps-grid {
    grid-size: 4 3;
    grid-gutter: 0 2;
    padding: 0 1;
}
.app-cell {
    height: 1;
    color: $text;
}
.app-cell.active {
    text-style: bold reverse;
    color: $accent;
}

#log-panel {
    border: round $secondary;
    padding: 0 1;
}
#cmd-log {
    height: 1fr;
    background: transparent;
}

#cmd-input {
    border: round $primary;
    height: 3;
}
"""


APP_CHOICES = [
    ("Netflix",  "netflix",  "1"),
    ("YouTube",  "youtube",  "2"),
    ("Prime",    "prime",    "3"),
    ("Plex",     "plex",     "4"),
    ("Disney+",  "disney",   "5"),
    ("Hulu",     "hulu",     "6"),
    ("HBO Max",  "max",      "7"),
    ("AppleTV",  "appletv",  "8"),
    ("Spotify",  "spotify",  "9"),
]


class TVConsole(App):
    CSS = CSS
    BINDINGS = [
        Binding("p", "toggle_play", "play/pause"),
        Binding("m", "mute", "mute"),
        Binding("up", "vol_up", "vol+", priority=True),
        Binding("down", "vol_down", "vol-", priority=True),
        Binding("h", "home_key", "home"),
        Binding("b", "back", "back"),
        Binding("e", "enter", "enter"),
        Binding("left", "left", "←"),
        Binding("right", "right", "→"),
        Binding("o", "power_off", "off"),
        Binding("w", "wake", "wake"),
        Binding("r", "refresh", "refresh"),
        Binding("k", "focus_input", "key/cmd"),
        Binding("q", "quit", "quit"),
        Binding("?", "show_help", "?"),
    ]
    for label, key, hk in APP_CHOICES:
        BINDINGS.append(Binding(hk, f"launch_{key}", f"{label}"))

    status_text = reactive("connecting...")
    reachable = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static(id="status-panel")
        yield Static(id="hotkeys-panel")
        yield Static(id="apps-panel")
        yield Vertical(Log(id="cmd-log"), id="log-panel")
        yield Input(placeholder="type a command (key KEY_NAME, app <name>, vol up N) -- Enter to send",
                    id="cmd-input")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "TV Console"
        self.render_hotkeys()
        self.render_apps()
        self.refresh_status()
        self.set_interval(2.0, self.refresh_status)

    # ---------- Rendering ----------
    def render_hotkeys(self):
        legend = (
            "[bold]p[/]:play/pause  [bold]m[/]:mute  [bold]↑↓[/]:vol  "
            "[bold]h[/]:home  [bold]b[/]:back  [bold]e[/]:enter  [bold]←→[/]:nav\n"
            "[bold]w[/]:wake  [bold]o[/]:off  [bold]r[/]:refresh  "
            "[bold]k[/]:cmd input  [bold]q[/]:quit  [bold]?[/]:help    "
            "[bold]1-9[/]:launch app"
        )
        self.query_one("#hotkeys-panel", Static).update(
            f"[$secondary]── Hotkeys ──[/]\n{legend}"
        )

    def render_apps(self):
        rows = []
        line = []
        for label, key, hk in APP_CHOICES:
            line.append(f"[bold]{hk}[/] {label}")
            if len(line) == 3:
                rows.append("   ".join(line))
                line = []
        if line:
            rows.append("   ".join(line))
        body = "\n".join(rows)
        self.query_one("#apps-panel", Static).update(
            f"[$secondary]── Apps ──[/]\n{body}"
        )

    def render_status(self, name, model, power, resolution, ip, app_hint, latency_ms):
        dot_color = "green" if power == "on" else ("yellow" if power == "standby" else "red")
        dot = f"[{dot_color}]●[/]"
        now = datetime.now().strftime("%H:%M:%S")
        line1 = f"[bold $accent]{name or '?'}[/]   {dot} [bold]{(power or '?').upper()}[/]   {model or '?'}"
        line2 = f"  {resolution or '?'}   ip:{ip or '?'}   {app_hint or ''}   ping:{latency_ms or '?'}ms   {now}"
        panel = self.query_one("#status-panel", Static)
        panel.update(f"[$secondary]── TV Status ──[/]\n{line1}\n{line2}")

    def log_line(self, msg, level="info"):
        log = self.query_one("#cmd-log", Log)
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "", "ok": "✓ ", "err": "✗ "}.get(level, "")
        log.write_line(f"{ts}  {prefix}{msg}")

    # ---------- Status polling ----------
    def refresh_status(self) -> None:
        env = t.load_env()
        host = env.get("TV_HOST")
        url = f"http://{host}:8001/api/v2/"
        t0 = time.perf_counter()
        info = None
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                info = json.loads(r.read())
            latency = int((time.perf_counter() - t0) * 1000)
            self.reachable = True
        except Exception:
            latency = None
            self.reachable = False
        if info:
            dev = info.get("device", {})
            self.render_status(
                name=dev.get("name"),
                model=dev.get("modelName"),
                power=dev.get("PowerState"),
                resolution=dev.get("resolution"),
                ip=dev.get("ip"),
                app_hint="",
                latency_ms=latency,
            )
        else:
            self.render_status(
                name="(unreachable)",
                model="?",
                power="off",
                resolution="?",
                ip=t.load_env().get("TV_HOST", "?"),
                app_hint="",
                latency_ms=None,
            )

    # ---------- Actions ----------
    def _safe(self, label, fn):
        try:
            fn()
            self.log_line(f"{label}", "ok")
        except Exception as e:
            self.log_line(f"{label} failed: {e}", "err")

    def action_toggle_play(self):
        # KEY_PLAY toggles on most Samsungs; if not, user can use 'k KEY_PAUSE' manually
        self._safe("play/pause", lambda: t.send_key("KEY_PLAY"))

    def action_mute(self):
        self._safe("mute", lambda: t.send_key("KEY_MUTE"))

    def action_vol_up(self):
        self._safe("vol up", lambda: t.send_key("KEY_VOLUP"))

    def action_vol_down(self):
        self._safe("vol down", lambda: t.send_key("KEY_VOLDOWN"))

    def action_home_key(self):
        self._safe("home", lambda: t.send_key("KEY_HOME"))

    def action_back(self):
        self._safe("back", lambda: t.send_key("KEY_RETURN"))

    def action_enter(self):
        self._safe("enter", lambda: t.send_key("KEY_ENTER"))

    def action_left(self):
        self._safe("←", lambda: t.send_key("KEY_LEFT"))

    def action_right(self):
        self._safe("→", lambda: t.send_key("KEY_RIGHT"))

    def action_wake(self):
        self._safe("wake (WoL)", t.wake)

    def action_power_off(self):
        self.log_line("WARNING: WSS power-off → deep sleep. Press 'o' again within 5s to confirm.", "err")
        if getattr(self, "_off_armed", 0) and time.time() - self._off_armed < 5:
            self._safe("power off (deep sleep)", t.power_off)
            self._off_armed = 0
        else:
            self._off_armed = time.time()

    def action_refresh(self):
        self.refresh_status()
        self.log_line("refresh", "ok")

    def action_focus_input(self):
        self.query_one("#cmd-input", Input).focus()

    def action_show_help(self):
        self.log_line(
            "Hotkeys: p=play  m=mute  ↑↓=vol  h=home  b=back  e=enter  ←→=nav  "
            "w=wake  o=off(2x)  r=refresh  1-9=apps  k=cmd input  q=quit",
        )

    # App launches
    def _make_app_action(key):
        def action(self):
            self._safe(f"app: {key}", lambda: t.launch_app(key))
        return action

    for label, key, hk in APP_CHOICES:
        locals()[f"action_launch_{key}"] = _make_app_action(key)

    # ---------- Manual command input ----------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.input.value = ""
        if not cmd:
            return
        self.log_line(f"> {cmd}")
        parts = cmd.split()
        head = parts[0].lower()
        try:
            if head == "key" and len(parts) >= 2:
                t.send_key(parts[1])
                self.log_line(f"sent: {parts[1]}", "ok")
            elif head == "app" and len(parts) >= 2:
                t.launch_app(parts[1])
                self.log_line(f"launched: {parts[1]}", "ok")
            elif head == "vol" and len(parts) >= 2:
                direction = parts[1]
                n = int(parts[2]) if len(parts) > 2 else 1
                k = "KEY_VOLUP" if direction == "up" else "KEY_VOLDOWN"
                for _ in range(n):
                    t.send_key(k)
                    time.sleep(0.12)
                self.log_line(f"vol {direction} x{n}", "ok")
            elif head in ("quit", "exit"):
                self.exit()
            elif head == "help":
                self.action_show_help()
            else:
                self.log_line(f"unknown: {cmd}  (try: key KEY_X | app NAME | vol up/down N | quit)", "err")
        except Exception as e:
            self.log_line(f"error: {e}", "err")


if __name__ == "__main__":
    TVConsole().run()
