#!/usr/bin/env python3
"""Shared browser setup for the Booksy session.

Booksy's login is behind hCaptcha, which fingerprints the browser rather than
just testing the human. Two things in a naive Playwright launch fail it
instantly:

1. A spoofed user-agent. Overriding the UA to a Chrome version that does not
   match the actual binary is a free tell -- the JS-visible Chromium version,
   the UA-CH client hints, and the claimed UA string all disagree. Do not set
   a user_agent here; let the real browser report itself.
2. Bundled Chromium plus the automation switches. `--enable-automation` and
   `navigator.webdriver` are read directly by bot detection.

So: drive the *installed Google Chrome* (channel="chrome"), strip the
automation switches, and leave the fingerprint alone.

INVARIANTS (an edit must not break these):
- Never set a user_agent override on these contexts. A UA that disagrees with
  the binary is worse than no override at all and was the original cause of
  "Request malformed - hCaptcha".
- login.py must stay headed. Headless Chrome is separately detectable and
  there is no way for Alex to solve a captcha he cannot see.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".booksy-profile"

# Switches Playwright adds by default that bot detection reads.
DROP_ARGS = ["--enable-automation", "--disable-extensions"]

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
]

# Removes the last obvious JS-visible automation marker before any page script
# runs. Chrome sets navigator.webdriver=true whenever it is driven by CDP.
STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
"""


def launch_profile(playwright, *, headless: bool):
    """Open the persistent Booksy profile in real Chrome.

    Falls back to bundled Chromium only if Chrome is missing, and says so --
    the fallback will very likely fail the captcha, and a silent downgrade
    would look like a mysterious login failure instead of a missing browser.
    """
    kwargs = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": headless,
        "args": STEALTH_ARGS,
        "ignore_default_args": DROP_ARGS,
        "viewport": {"width": 1280, "height": 900},
    }
    try:
        ctx = playwright.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception as exc:  # noqa: BLE001 - report and degrade loudly
        print(f"note: real Chrome unavailable ({type(exc).__name__}); falling back to")
        print("      bundled Chromium, which will probably fail hCaptcha.")
        ctx = playwright.chromium.launch_persistent_context(**kwargs)

    ctx.add_init_script(STEALTH_INIT)
    return ctx
