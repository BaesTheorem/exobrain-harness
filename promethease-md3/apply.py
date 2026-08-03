#!/usr/bin/env python3
"""Apply the Material Design overhaul to a Promethease report.

The overhaul is a single <style> + <script> block injected just before the
closing </body>. The report's own markup, data and JavaScript are left byte
for byte alone, so the change is reversible and cannot break the report's
logic.

    apply.py report.html                 # in place, keeps report.original.html
    apply.py report.html -o themed.html  # write a copy instead
    apply.py ~/Downloads/*.html          # several at once
    apply.py report.html --check         # report status, change nothing
    apply.py report.html --revert        # strip the overhaul back out

Reports are typically 10-30 MB because the genome data is embedded, so
everything here streams through memory once and writes once.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "overlay.html"

BEGIN = "<!-- BEGIN promethease-md3"
END = "<!-- END promethease-md3 -->"
# Consumes the newlines inject() adds on both sides, so strip -> inject is a
# byte-exact round trip and re-applying never accumulates blank lines.
BLOCK_RE = re.compile(
    r"\n?" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL
)
VERSION_RE = re.compile(re.escape(BEGIN) + r"\s+([0-9][^\s-]*)")
BODY_RE = re.compile(r"(\n[ \t]*)?</body\s*>", re.IGNORECASE)

# Markup every Promethease report has and nothing else plausibly does.
FINGERPRINTS = ('id="genoslist"', "snpedia", "boxresult")


class Skip(Exception):
    """Non-fatal: report it and move on to the next file."""


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise Skip(f"cannot read: {exc}") from exc


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", errors="surrogateescape")


def installed_version(html: str) -> str | None:
    match = VERSION_RE.search(html)
    if match:
        return match.group(1)
    return "unknown" if BEGIN in html else None


def looks_like_promethease(html: str) -> bool:
    head = html[:400_000].lower()
    return sum(fp.lower() in head for fp in FINGERPRINTS) >= 2


def strip_overlay(html: str) -> str:
    return BLOCK_RE.sub("", html)


def inject(html: str, overlay: str) -> str:
    """Insert before the last </body>. Expects an already-stripped document."""
    matches = list(BODY_RE.finditer(html))
    if not matches:
        raise Skip("no </body> tag found; is this a complete HTML report?")
    at = matches[-1].start()
    return html[:at] + "\n" + overlay.strip() + "\n" + html[at:]


def backup_path(path: Path) -> Path:
    return path.with_name(path.stem + ".original" + path.suffix)


def human(nbytes: int) -> str:
    return f"{nbytes / 1_048_576:.1f} MB"


def process(path: Path, args: argparse.Namespace, overlay: str, version: str) -> None:
    if not path.is_file():
        raise Skip("not a file")

    html = read(path)
    current = installed_version(html)
    # Sniff the report itself; our own block mentions the same markers.
    stock = strip_overlay(html) if current else html

    if args.check:
        kind = "Promethease report" if looks_like_promethease(stock) else "not a Promethease report"
        state = f"overhauled (v{current})" if current else "stock"
        print(f"{path.name}: {state}, {kind}, {human(len(html))}")
        return

    if args.revert:
        if not current:
            raise Skip("no overhaul to revert")
        write(path, stock)
        print(f"{path.name}: reverted to stock (was v{current})")
        return

    if not looks_like_promethease(stock) and not args.force:
        raise Skip(
            "does not look like a Promethease report "
            "(no #genoslist / SNPedia markers) -- use --force to apply anyway"
        )

    out = Path(args.output) if args.output else path
    in_place = out == path

    # Only snapshot a genuinely stock file, so re-running never overwrites the
    # real original with an already-themed copy.
    if in_place and not args.no_backup and current is None:
        backup = backup_path(path)
        if not backup.exists():
            write(backup, html)
            print(f"{path.name}: saved original to {backup.name}")

    write(out, inject(stock, overlay))

    if current == version:
        verb = f"re-applied v{version}"
    elif current:
        verb = f"upgraded v{current} -> v{version}"
    else:
        verb = f"applied v{version}"
    where = "in place" if in_place else f"-> {out.name}"
    print(f"{path.name}: {verb} {where}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Material Design overhaul for Promethease reports.",
        epilog="Re-running is safe: an existing overhaul is replaced, not stacked.",
    )
    parser.add_argument("reports", nargs="+", type=Path, help="report HTML file(s)")
    parser.add_argument("-o", "--output", help="write here instead of in place (single input only)")
    parser.add_argument("--check", action="store_true", help="report status, change nothing")
    parser.add_argument("--revert", action="store_true", help="strip the overhaul back out")
    parser.add_argument("--no-backup", action="store_true", help="skip the .original.html snapshot")
    parser.add_argument("--force", action="store_true", help="apply even if the file fails the sniff test")
    args = parser.parse_args()

    if args.output and len(args.reports) > 1:
        parser.error("-o takes a single input file")
    if args.check and args.revert:
        parser.error("--check and --revert are mutually exclusive")

    try:
        overlay = OVERLAY.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {OVERLAY}: {exc}", file=sys.stderr)
        return 2
    version = (VERSION_RE.search(overlay).group(1) if VERSION_RE.search(overlay) else "unknown")

    failures = 0
    for path in args.reports:
        try:
            process(path, args, overlay, version)
        except Skip as exc:
            print(f"{path.name}: skipped -- {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
