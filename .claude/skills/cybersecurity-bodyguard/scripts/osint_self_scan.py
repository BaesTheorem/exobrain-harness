#!/usr/bin/env python3
"""
OSINT self-scan for the cybersecurity-bodyguard skill.

Reads targets from targets.json (gitignored) and performs passive reconnaissance
against public sources only. NEVER scrapes harassment forums, NEVER attempts to
identify attackers, NEVER performs any offensive action.

Outputs a structured JSON report that the skill uses to write the Security Log.

Usage:
    python3 osint_self_scan.py                  # full scan
    python3 osint_self_scan.py --mode breach    # HIBP only (for daily checks)
    python3 osint_self_scan.py --mode brokers   # data-broker reappearance check
    python3 osint_self_scan.py --dry-run        # print plan without executing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
TARGETS_PATH = SKILL_DIR / "targets.json"
TARGETS_EXAMPLE = SKILL_DIR / "targets.example.json"

# HIBP API — requires HIBP_API_KEY env var (free tier: $3.95/month)
HIBP_ENDPOINT = "https://haveibeenpwned.com/api/v3/breachedaccount/{email}"

# Data brokers to check via Google dorks. We do not hit broker sites directly —
# Google's indexed view is sufficient for presence detection and avoids
# creating broker-side records of the query.
BROKER_DOMAINS = [
    "spokeo.com",
    "beenverified.com",
    "whitepages.com",
    "fastpeoplesearch.com",
    "radaris.com",
    "mylife.com",
    "peoplefinders.com",
    "intelius.com",
    "truepeoplesearch.com",
    "familytreenow.com",
    "thatsthem.com",
]


def load_targets() -> dict[str, Any]:
    if not TARGETS_PATH.exists():
        print(
            f"[!] No targets.json found at {TARGETS_PATH}\n"
            f"    Copy {TARGETS_EXAMPLE.name} to targets.json and fill in the fields.",
            file=sys.stderr,
        )
        sys.exit(1)
    with TARGETS_PATH.open() as fh:
        return json.load(fh)


def hibp_check(email: str, api_key: str) -> list[dict[str, Any]]:
    """Return list of breaches for an email. Empty list if clean."""
    url = HIBP_ENDPOINT.format(email=urllib.parse.quote(email))
    req = urllib.request.Request(
        url,
        headers={
            "hibp-api-key": api_key,
            "user-agent": "exobrain-bodyguard/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # not pwned
        if e.code == 429:
            time.sleep(6)  # HIBP rate limit: 1 req / 6s on consumer tier
            return hibp_check(email, api_key)
        raise


def build_google_dorks(targets: dict[str, Any]) -> list[dict[str, str]]:
    """
    Produce a list of Google search queries to run.

    We do NOT execute these — that requires WebSearch, which the skill drives
    via Claude. This function just builds the query plan.
    """
    dorks: list[dict[str, str]] = []
    names = targets.get("names", [])
    emails = targets.get("emails", [])
    phones = targets.get("phones", [])
    usernames = targets.get("usernames", [])
    city = targets.get("city", "")
    employer = targets.get("employer", "")

    # Name + location
    for name in names:
        if city:
            dorks.append(
                {
                    "category": "name_location",
                    "query": f'"{name}" "{city}"',
                    "why": "Anyone indexing name+city is building a profile",
                }
            )
        if employer:
            dorks.append(
                {
                    "category": "name_employer",
                    "query": f'"{name}" "{employer}"',
                    "why": "Workplace pivot",
                }
            )
        dorks.append(
            {
                "category": "name_files",
                "query": f'"{name}" (filetype:pdf OR filetype:xlsx OR filetype:csv)',
                "why": "Leaked rosters, directories, spreadsheets",
            }
        )

    # Direct identifiers
    for email in emails:
        dorks.append(
            {
                "category": "email",
                "query": f'"{email}"',
                "why": "Any public mention of this email",
            }
        )
    for phone in phones:
        dorks.append(
            {
                "category": "phone",
                "query": f'"{phone}"',
                "why": "Phone exposure",
            }
        )

    # Usernames
    for username in usernames:
        dorks.append(
            {
                "category": "username",
                "query": f'"{username}"',
                "why": "Username leak across sites",
            }
        )
        dorks.append(
            {
                "category": "username_github",
                "query": f'"{username}" site:github.com',
                "why": "Username tied to code identity",
            }
        )

    # Paste sites (all usernames + emails)
    paste_domains = "site:pastebin.com OR site:ghostbin.com OR site:paste.ee OR site:hastebin.com"
    for identifier in usernames + emails:
        dorks.append(
            {
                "category": "paste",
                "query": f'"{identifier}" ({paste_domains})',
                "why": "Pastebin dumps (credentials, doxx prep)",
            }
        )

    # Data brokers
    for name in names:
        for broker in BROKER_DOMAINS:
            dorks.append(
                {
                    "category": "broker",
                    "broker": broker,
                    "query": f'"{name}" site:{broker}',
                    "why": f"Presence on {broker}",
                }
            )

    return dorks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["full", "breach", "brokers", "plan"],
        default="full",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = load_targets()
    report: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": args.mode,
        "findings": {},
    }

    # 1. Breach check (HIBP)
    if args.mode in {"full", "breach"}:
        api_key = os.environ.get("HIBP_API_KEY")
        if not api_key:
            report["findings"]["hibp"] = {
                "error": "HIBP_API_KEY not set in environment",
                "guidance": "Subscribe at https://haveibeenpwned.com/API/Key",
            }
        elif args.dry_run:
            report["findings"]["hibp"] = {
                "plan": f"Would check {len(targets.get('emails', []))} emails",
            }
        else:
            hibp_results = {}
            for email in targets.get("emails", []):
                hibp_results[email] = hibp_check(email, api_key)
                time.sleep(6.5)  # respect rate limit
            report["findings"]["hibp"] = hibp_results

    # 2. Google dork plan
    if args.mode in {"full", "brokers", "plan"}:
        dorks = build_google_dorks(targets)
        if args.mode == "brokers":
            dorks = [d for d in dorks if d["category"] == "broker"]
        report["findings"]["google_dorks"] = {
            "count": len(dorks),
            "queries": dorks,
            "note": (
                "These queries are the plan. The skill executes them via "
                "WebSearch so results can be assessed by Claude. This script "
                "does not hit Google directly."
            ),
        }

    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
