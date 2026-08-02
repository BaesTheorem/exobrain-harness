#!/usr/bin/env python3
"""
Assist with the Missouri DES UInteract portal (uinteract.labor.mo.gov).

WHAT THIS DOES NOT DO
---------------------
It never submits a weekly request for payment. That form is a sworn statement
under RSMo 288.380, and several of its questions (earnings, self-employment,
severance, availability) have answers only Alex knows. This tool logs in,
surfaces the claim state, and parks a real browser on the form. A human answers
and clicks submit.

THE RENDERING GOTCHA (learned the hard way, 2026-08-02)
-------------------------------------------------------
UInteract's Angular app blanks itself to about:blank unless the page was opened
by Chrome itself. Specifically:

  * playwright.chromium.launch_persistent_context(...)  -> blank page
  * browser.new_page() over CDP                          -> blank page
  * URL passed on the Chrome command line, then attach   -> RENDERS FINE

So the only working pattern is: spawn real Google Chrome with the target URL as
an argv, wait, then connect_over_cdp and drive the page that already exists.
Never call new_page() against this site. Also note connect_over_cdp sometimes
fails on a second attach with "Browser context management is not supported" --
relaunch Chrome rather than reattaching.

Subcommands:
  open      Launch Chrome, log in, and leave the session open for Alex.
  status    Log in, print the claimant homepage + claim state, leave it open.
  weeks     Print recent week-ending Saturdays and their 14-day deadlines.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
PROFILE = HERE / ".chrome-profile"
SHOTS = HERE / "screenshots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
LOGIN_URL = "https://uinteract.labor.mo.gov/benefits/#/benefits/login"


def load_env():
    env = {}
    f = HARNESS / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def creds():
    env = load_env()
    u = os.environ.get("UINTERACT_USERNAME") or env.get("UINTERACT_USERNAME")
    p = os.environ.get("UINTERACT_PASSWORD") or env.get("UINTERACT_PASSWORD")
    if not u or not p:
        sys.exit(f"Missing UINTERACT_* creds in {HARNESS/'.env'} (gitignored).")
    return u, p


def spawn_chrome(url):
    """Launch real Chrome with the URL on the command line. See the gotcha above."""
    subprocess.run(["pkill", "-f", f"remote-debugging-port={PORT}"],
                   capture_output=True)
    time.sleep(2)
    PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [CHROME, f"--remote-debugging-port={PORT}",
         f"--user-data-dir={PROFILE}", "--no-first-run",
         "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(14)


def attach(pw):
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = b.contexts[0]
    pages = [p for p in ctx.pages if not p.is_closed()]
    if not pages:
        sys.exit("No Chrome page target. Relaunch.")
    return b, ctx, pages[-1]


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    p = SHOTS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
        print(f"  [shot] {p}")
    except Exception as e:
        print(f"  [shot failed] {e}")


def text_of(page):
    try:
        return page.evaluate("()=>document.body?document.body.innerText:''")
    except Exception:
        return ""


def do_login(page, u, p):
    if page.locator("input").count() == 0:
        print("! Page is blank. This is the rendering gotcha -- the page must be")
        print("  opened by Chrome itself, not created over CDP.")
        return False
    if not re.search(r"USER ID", text_of(page), re.I):
        print("✓ Already past the login screen.")
        return True
    page.locator("input").nth(0).fill(u)
    page.locator("input[type=password]").first.fill(p)
    print("✓ Credentials entered.")
    try:
        page.get_by_role("button", name=re.compile(r"^log ?in$", re.I)).first.click()
    except Exception:
        page.locator("input[type=password]").first.press("Enter")
    time.sleep(10)
    return True


def cmd_open(args):
    from playwright.sync_api import sync_playwright
    u, p = creds()
    spawn_chrome(LOGIN_URL)
    with sync_playwright() as pw:
        _, ctx, page = attach(pw)
        do_login(page, u, p)
        live = [x for x in ctx.pages if not x.is_closed()]
        if live:
            page = live[-1]
            print("url:", page.url)
            print("=== SCREEN ===")
            print(text_of(page)[:3000])
            shot(page, "session")
        else:
            print("! Chrome closed its page target after login.")
    print("\nChrome is left running for Alex. It is NOT going to submit anything.")


def cmd_status(args):
    cmd_open(args)


def cmd_weeks(args):
    today = date.today()
    last_sat = today - timedelta(days=(today.weekday() - 5) % 7)
    if last_sat >= today:
        last_sat -= timedelta(days=7)
    print("Week ending (Sat)   Covers                     Request deadline")
    for i in range(4):
        s = last_sat - timedelta(days=7 * i)
        print(f"  {s:%Y-%m-%d}        {s - timedelta(days=6):%m/%d}-{s:%m/%d}"
              f"                {s + timedelta(days=14):%Y-%m-%d}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("open").set_defaults(func=cmd_open)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("weeks").set_defaults(func=cmd_weeks)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
