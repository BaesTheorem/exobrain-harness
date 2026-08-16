#!/usr/bin/env python3
"""One-time Booksy login into a persistent browser profile.

Booksy has no public auth API and no documented token exchange. Its login runs
in an isolated microfrontend iframe (cx-onboarding-microfrontend.booksy.com)
with its own flow, and it can demand an SMS code. Scraping a bearer token out
of that would be fragile and would break the first time Booksy changed it.

So instead of storing credentials, Alex logs in once by hand into a Chromium
profile that lives on disk here, and every later booking reuses that logged-in
session. No password, no token, no 2FA replay ever touches this repo.

INVARIANTS (an edit must not break these):
- Nothing in this package ever reads, stores, prompts for, or logs a Booksy
  password, SMS code, or bearer token. The browser profile holds the session
  and the profile directory is gitignored.
- This script is interactive and headed by design. Never make it headless or
  autofill a credential field -- that would defeat the whole point.

Usage:
    python3 login.py              # opens a window; log in, then it verifies
    python3 login.py --check      # headless: is the saved session still good?
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".booksy-profile"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
HOME = "https://booksy.com/en-us/"
ME_ENDPOINT = "https://us.booksy.com/core/v2/customer_api/me"
WEB_API_KEY = "web-e3d812bf-d7a2-445d-ab38-55589ae6a121"


def session_identity(page) -> dict | None:
    """Ask Booksy who we are, using the browser's own session.

    Returns the account payload when logged in, else None. Run from inside the
    page so the session's auth headers/cookies are applied by Booksy's own
    fetch wrapper rather than reconstructed by us.
    """
    return page.evaluate(
        """async ([url, key]) => {
            try {
                const r = await fetch(url, {
                    headers: {'x-api-key': key, 'accept': 'application/json'},
                    credentials: 'include',
                });
                if (!r.ok) return null;
                return await r.json();
            } catch (e) { return null; }
        }""",
        [ME_ENDPOINT, WEB_API_KEY],
    )


def describe(identity: dict | None) -> str:
    if not identity:
        return "not logged in"
    account = identity.get("account") or identity.get("customer") or identity
    name = account.get("first_name") or account.get("name") or "(unnamed)"
    return f"logged in as {name}"


def check() -> int:
    if not PROFILE_DIR.exists():
        print("no saved session; run: python3 login.py")
        return 1
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=True, user_agent=UA
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        identity = session_identity(page)
        ctx.close()
    print(describe(identity))
    return 0 if identity else 1


def interactive() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening Booksy. Log in (email or phone + the SMS code if it asks).")
    print("Leave the window open until this says it worked -- checking every 5s.\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)

        identity = None
        for _ in range(120):  # ~10 minutes
            page.wait_for_timeout(5000)
            try:
                identity = session_identity(page)
            except Exception:  # noqa: BLE001 - page may be mid-navigation
                continue
            if identity:
                break

        print(f"\n{describe(identity)}")
        if identity:
            print(f"Session saved to {PROFILE_DIR.name}/ -- MIST can book from now on.")
        else:
            print("Timed out without a login. Re-run when you have a minute.")
        ctx.close()
    return 0 if identity else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Log in to Booksy once, reuse the session.")
    parser.add_argument("--check", action="store_true", help="test the saved session")
    args = parser.parse_args(argv)
    return check() if args.check else interactive()


if __name__ == "__main__":
    sys.exit(main())
