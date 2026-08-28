#!/usr/bin/env python3
"""Generic native window shell for local web apps (the house "flask app" pattern).

Ensures a launchd-managed server is up, then shows it in a WKWebView window
via pywebview. Configuration comes from environment variables set by the app
bundle's launch script:

  APPSHELL_TITLE   window + process title            (required)
  APPSHELL_URL     UI url, e.g. http://127.0.0.1:5025/   (required)
  APPSHELL_HEALTH  health probe url                  (default: APPSHELL_URL)
  APPSHELL_LABEL   launchd label to bootstrap/kickstart when down (optional)
  APPSHELL_PLIST   plist path for bootstrap          (optional)
  APPSHELL_LOG     server log to open on failure     (optional)
  APPSHELL_W/H     window size                       (default 1280x860)

The server is NOT run in-process: these servers already live under launchd
(pipelines, VPN gates, KeepAlive). The shell only pokes launchd over its
public interface and speaks HTTP to localhost, so it needs no TCC grants.
"""

import os
import subprocess
import sys
import time
import urllib.request

TITLE = os.environ.get("APPSHELL_TITLE", "App")
URL = os.environ["APPSHELL_URL"]
HEALTH = os.environ.get("APPSHELL_HEALTH", URL)
LABEL = os.environ.get("APPSHELL_LABEL", "")
PLIST = os.environ.get("APPSHELL_PLIST", "")
SERVER_LOG = os.environ.get("APPSHELL_LOG", "")
WIN_W = int(os.environ.get("APPSHELL_W", "1280"))
WIN_H = int(os.environ.get("APPSHELL_H", "860"))

try:
    import setproctitle
    setproctitle.setproctitle(TITLE)
except ImportError:
    pass


def up(timeout=1.5):
    try:
        urllib.request.urlopen(HEALTH, timeout=timeout)
        return True
    except Exception:
        return False


def die(msg):
    subprocess.run([
        "osascript", "-e",
        f'display alert "{TITLE} failed to start" message "{msg}"',
    ], check=False)
    if SERVER_LOG and os.path.exists(SERVER_LOG):
        subprocess.run(["open", SERVER_LOG], check=False)
    sys.exit(1)


def ensure_server():
    if up():
        return
    if not LABEL:
        die(f"Nothing is answering at {HEALTH} and no launchd label is configured.")
    uid = os.getuid()
    if PLIST:
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST],
                       capture_output=True)  # no-op if already loaded
    kick = subprocess.run(["launchctl", "kickstart", f"gui/{uid}/{LABEL}"],
                          capture_output=True)
    if kick.returncode != 0:
        die(f"launchctl could not start {LABEL}. Is its plist installed?")
    for _ in range(40):
        if up():
            return
        time.sleep(0.5)
    tail = ""
    if SERVER_LOG and os.path.exists(SERVER_LOG):
        with open(SERVER_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(SERVER_LOG) - 600))
            tail = f.read().decode("utf-8", "replace").replace('"', "'")[-400:]
    die(f"The server never came up at {HEALTH}. {tail}")


def _macos_identity():
    """Menu-bar name + Dock icon. The bundle's executable re-execs the brew
    Python framework, so AppKit reads Python.app's Info.plist; patch the
    in-memory bundle dict and set the Dock icon before the run loop starts."""
    try:
        from Foundation import NSBundle
        bundle = NSBundle.mainBundle()
        for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
            if info:
                info["CFBundleName"] = TITLE
                info["CFBundleDisplayName"] = TITLE
        icon = os.environ.get("APPSHELL_ICON", "")
        if icon and os.path.exists(icon):
            from AppKit import NSApplication, NSImage
            img = NSImage.alloc().initWithContentsOfFile_(icon)
            if img:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass  # cosmetic only; never block the window


def main():
    ensure_server()
    _macos_identity()
    import webview
    webview.create_window(TITLE, URL, width=WIN_W, height=WIN_H,
                          min_size=(900, 640))
    webview.start()


if __name__ == "__main__":
    main()
