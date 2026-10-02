#!/usr/bin/env python3
"""Pair this Mac with the PS5 for Remote Play, with no interactive terminal.

pyremoteplay's own CLI pairs through ``input()`` prompts, which a Console chat cannot
answer. This splits the flow into commands that take their inputs as arguments:

1. ``ps5-pair.py login-url`` prints the PSN sign-in URL. Sign in with the PlayStation
   account. The browser lands on a redirect page that can look like an error; copy the
   full URL from the address bar.
2. On the PS5: Settings > System > Remote Play > Link Device. An 8-digit PIN appears.
3. ``ps5-pair.py register --redirect-url '<url>' --pin 12345678`` exchanges the sign-in
   code for the account id, then registers with the console while the PIN screen is open.
4. ``ps5-pair.py status`` shows the console status and the registered users.

Credentials land in ``~/.pyremoteplay/.profile.json``. That file is a secret and never
goes in the repo. Run with the ``playstation/.venv`` interpreter.
"""

from __future__ import annotations

import argparse
import logging

from pyremoteplay import RPDevice
from pyremoteplay.oauth import get_login_url
from pyremoteplay.profile import Profiles

from ps5lib import fail, resolve_host

REDIRECT_PREFIX = "https://remoteplay.dl.playstation.net/remoteplay/redirect"


def cmd_login_url(_: argparse.Namespace) -> None:
    print(get_login_url())


def cmd_status(args: argparse.Namespace) -> None:
    device = RPDevice(args.host)
    status = device.get_status()
    if not status:
        fail(f"no answer from {args.host} (UDP 9302)")
    print(
        f"{device.host_name} ({device.host_type}) at {device.host}: {device.status_name}"
    )
    print(
        f"system version {device.system_version}, app: {device.app_name or '(home screen)'}"
    )
    profiles = Profiles.load()
    users = profiles.usernames
    print(
        f"profiles file: {Profiles.default_path() or '~/.pyremoteplay/.profile.json'}"
    )
    if not users:
        print("registered users: none (run login-url, then register)")
        return
    for name in users:
        hosts = [h.name for h in profiles.get_user_profile(name).hosts]
        print(f"user {name}: registered hosts {hosts or 'none'}")


def cmd_register(args: argparse.Namespace) -> None:
    if not args.pin.isdigit() or len(args.pin) != 8:
        fail("the PIN is the 8-digit number on the PS5 Link Device screen")
    profiles = Profiles.load()
    if args.redirect_url:
        if not args.redirect_url.startswith(REDIRECT_PREFIX):
            fail(f"the redirect URL must start with {REDIRECT_PREFIX}")
        profile = profiles.new_user(args.redirect_url)
        if profile is None:
            fail("PSN sign-in exchange failed (the code is single use; sign in again)")
        print(f"PSN account resolved: {profile.name}")
        user = profile.name
    else:
        users = profiles.usernames
        if not users:
            fail("no PSN profile yet; pass --redirect-url from the login-url sign-in")
        user = args.user or users[0]
    device = RPDevice(args.host)
    if not device.get_status():
        fail(f"no answer from {args.host}; is the PS5 on?")
    result = device.register(user, args.pin, timeout=args.timeout, profiles=profiles)
    if result is None:
        fail("registration failed; the Link Device screen must be open with this PIN")
    print(f"Registered {user} with {device.host_name} at {device.host}.")
    print("Next: ps5-smoke.py to stream a few frames and tap a button.")


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--host", help="PS5 address; default $PS5_HOST or LAN discovery"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login-url", help="print the PSN sign-in URL").set_defaults(
        func=cmd_login_url
    )
    sub.add_parser("status", help="console status and registered users").set_defaults(
        func=cmd_status
    )
    reg = sub.add_parser("register", help="register this Mac with the console")
    reg.add_argument(
        "--redirect-url", help="URL the browser landed on after PSN sign-in"
    )
    reg.add_argument(
        "--user", help="existing profile name (when --redirect-url is omitted)"
    )
    reg.add_argument("--pin", required=True, help="8-digit PIN from Link Device")
    reg.add_argument("--timeout", type=float, default=5.0)
    reg.set_defaults(func=cmd_register)
    args = parser.parse_args()
    args.host = resolve_host(args.host)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
