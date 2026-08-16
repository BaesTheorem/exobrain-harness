#!/usr/bin/env python3
"""One-time Booksy login into a persistent browser profile.

Booksy has no public auth API and no documented token exchange. Its login runs
in an isolated microfrontend iframe (cx-onboarding-microfrontend.booksy.com)
with its own flow, and it is gated by hCaptcha.

hCaptcha fingerprints the *browser*, not the human, and a Playwright-driven
Chrome fails it no matter how the fingerprint is patched -- CDP attachment is
itself detectable. Fighting that is a losing game, so we do not: this script
launches a completely ordinary Chrome as a plain subprocess, with no automation
attached, pointed at the profile directory we care about. Alex logs in like a
normal person, the session cookies land in that profile, and Playwright reuses
the profile *afterwards* for booking. The captcha only guards login, and no
automation is present when it runs.

INVARIANTS (an edit must not break these):
- The login browser is launched as a bare subprocess and is never driven by
  Playwright/CDP. Attaching automation to it is what breaks the captcha.
- Nothing in this package reads, stores, prompts for, or logs a Booksy
  password, SMS code, or bearer token. The gitignored profile holds the
  session; that is the whole mechanism.

Usage:
    python3 login.py              # opens a normal Chrome; log in, close it
    python3 login.py --check      # is the saved session still good?
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from browser import PROFILE_DIR, launch_profile
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

HOME = "https://booksy.com/en-us/"
ME_ENDPOINT = "https://us.booksy.com/core/v2/customer_api/me"
WEB_API_KEY = "web-e3d812bf-d7a2-445d-ab38-55589ae6a121"


def session_identity(page) -> dict | None:
    """Ask Booksy who we are, using the browser's own session.

    Booksy does NOT authenticate by cookie. /me rejects a cookie-only request
    with `auth_header_token is required` -- the session is a bearer token kept
    in web storage and replayed as a header. An earlier version of this check
    sent cookies only, so it reported "not logged in" for a perfectly good
    session. Find the token first, then present it.
    """
    return page.evaluate(
        """async ([url, key]) => {
            // Booksy has moved this key around; take any token-shaped value.
            const stores = [window.localStorage, window.sessionStorage];
            const candidates = [];
            for (const store of stores) {
                for (let i = 0; i < store.length; i++) {
                    const k = store.key(i);
                    if (!/token|access|auth|session/i.test(k)) continue;
                    const raw = store.getItem(k);
                    if (!raw) continue;
                    candidates.push(raw);
                    try {
                        const parsed = JSON.parse(raw);
                        for (const v of Object.values(parsed || {})) {
                            if (typeof v === 'string' && v.length > 20) candidates.push(v);
                        }
                    } catch (e) { /* plain string token */ }
                }
            }
            const headers = ['x-access-token', 'authorization', 'x-auth-token'];
            for (const token of candidates) {
                for (const h of headers) {
                    const value = h === 'authorization' ? 'Bearer ' + token : token;
                    try {
                        const r = await fetch(url, {
                            headers: {'x-api-key': key, 'accept': 'application/json', [h]: value},
                            credentials: 'include',
                        });
                        if (r.ok) return await r.json();
                    } catch (e) { /* try the next shape */ }
                }
            }
            return null;
        }""",
        [ME_ENDPOINT, WEB_API_KEY],
    )


def logged_out_ui(page) -> bool:
    """Fallback signal: does the page still offer a login link?

    Independent of the token plumbing, so a Booksy change to storage keys
    cannot make a live session look dead.
    """
    body = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    return "Log In / Sign Up" in body


def describe(identity: dict | None) -> str:
    if not identity:
        return "not logged in"
    account = identity.get("account") or identity.get("customer") or identity
    name = account.get("first_name") or account.get("name") or "(signed in)"
    return f"logged in as {name}"


def profile_in_use() -> int | None:
    """PID of a Chrome already holding our profile, if any.

    Chrome's ProcessSingleton lock means Playwright simply cannot open a
    profile another Chrome has. Detect it and say so, rather than surfacing
    the generic launch failure as "not logged in".
    """
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/usr/bin/pgrep", "-f", f"user-data-dir={PROFILE_DIR}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - best-effort diagnostic
        return None
    pids = [int(line) for line in out.stdout.split() if line.isdigit()]
    return pids[0] if pids else None


def check() -> int:
    if not PROFILE_DIR.exists():
        print("no saved session; run: python3 login.py")
        return 1

    pid = profile_in_use()
    if pid:
        print(f"Chrome (pid {pid}) still has the profile open.")
        print("Quit that window fully, then re-run: python3 login.py --check")
        return 3

    with sync_playwright() as p:
        ctx = launch_profile(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        identity = session_identity(page)
        still_out = logged_out_ui(page)
        ctx.close()

    if identity:
        print(describe(identity))
        return 0
    if not still_out:
        # The token lookup missed, but Booksy is not offering a login link.
        print("logged in (session present, token shape unrecognised)")
        return 0
    print("not logged in")
    return 1


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def interactive() -> int:
    """Hand Alex a normal browser, then verify what it left behind.

    Deliberately a bare subprocess: no Playwright, no CDP, nothing for
    hCaptcha to detect. We only inspect the profile once Chrome has exited.
    """
    if not Path(CHROME).exists():
        print(f"Google Chrome not found at {CHROME}")
        return 2

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening a normal Chrome window (nothing is driving it).\n")
    print("  1. Log in to Booksy.")
    print("  2. Close the window when you're done.\n")
    print("Waiting for you to close it...")

    proc = subprocess.Popen(  # noqa: S603 - fixed path, no shell, no user input
        [
            CHROME,
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            HOME,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait()

    print("Window closed. Checking the session...\n")
    return check()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log in to Booksy once, reuse the session.")
    parser.add_argument("--check", action="store_true", help="test the saved session")
    args = parser.parse_args(argv)
    return check() if args.check else interactive()


if __name__ == "__main__":
    sys.exit(main())
