#!/usr/bin/env python3
"""Full-page screenshot of a job posting, kept with its listing note.

Alex asked (2026-10-22) for a record of each qualifying posting as the
employer showed it, the pay range most of all. Postings change or vanish
during an interview process, and the raw JD callout is text only: it does
not prove what the page said, and some ATS pages print the band outside the
JD body, so the text copy can miss it.

The script reads the note's posting URL (`original_listing`, then
`listing_url`, then `apply_url`, or `--url`), loads it in headless Chrome
(patchright, normal UA, no window), opens "show more" type expanders,
scrolls to the end so lazy content loads, and saves one full-page PNG.

Where the PNG goes: the listing's own folder, `Job Listings/<Company> - <Role>/`,
as an artifact. A flat note is promoted into that folder first (Alex
2026-10-22: make the folder at once for every qualifying JD). Wikilinks
resolve by basename, so the move breaks no link.

The comp check is the positive control. The script reads the page text and
looks for `comp_min` or `comp_max` from the frontmatter in any dollar figure
(annual, "85K", or hourly x 2080). Results:
  seen       a figure on the page matches the note's band
  not-found  the note has a band but the page does not show it (exit 1)
  unlisted   the note has no listed band (comp_listed false)
It also reports a page that says the posting is closed.

The note gets `jd_snapshot`, `jd_snapshot_date`, `jd_snapshot_comp` in the
frontmatter and a collapsed callout under `## Listing snapshots`, one per
run, so a repost adds a second dated image and keeps the first.

Usage:
    python3 jd-snapshot.py --note "<listing note path>" [--url URL] [--dry-run]

Exit: 0 saved and comp seen (or unlisted), 1 saved but comp not found,
2 nothing saved (load failed, or the page says the posting is closed or gone;
then the note is not moved and the capture stays in tmp/jd-snapshot).

INVARIANTS:
- Headless only. Never open a visible browser window.
- Never overwrite an older snapshot; each run writes a new dated file.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

UV = os.environ.get("UV", str(Path.home() / ".local/bin/uv"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")  # headless says "HeadlessChrome"
EXPANDERS = re.compile(r"^\s*(show|see|read|view) (more|full|all)( description| details)?\s*$", re.I)
CLOSED = re.compile(r"no longer (accepting|open|available)|position (has been )?filled"
                    r"|job (is )?(closed|expired)|posting (has )?expired|(job|page) not found"
                    r"|job you requested was not found", re.I)
DOLLAR = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?")


def _ensure_patchright() -> None:
    """Re-run this script under uv with patchright when it is not importable."""
    try:
        import patchright  # noqa: F401  (import probe only)
    except ImportError:
        if os.environ.get("JDSNAP_REEXEC"):
            print("jd-snapshot DID NOT RUN: patchright is not available under uv.")
            sys.exit(2)
        os.environ["JDSNAP_REEXEC"] = "1"
        os.execv(UV, [UV, "run", "--no-project", "--quiet", "--python", "3.12",
                      "--with", "patchright", "python", __file__, *sys.argv[1:]])


def frontmatter(txt: str) -> tuple[str, int]:
    m = re.match(r"---\n(.*?)\n---\n", txt, re.S)
    return (m.group(1), m.end()) if m else ("", 0)


def field(fm: str, key: str) -> str:
    m = re.search(r"^%s:[ \t]*(.*)$" % re.escape(key), fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def set_field(fm: str, key: str, value: str) -> str:
    line = f'{key}: "{value}"'
    if re.search(r"^%s:" % re.escape(key), fm, re.M):
        return re.sub(r"^%s:.*$" % re.escape(key), lambda _: line, fm, count=1, flags=re.M)
    return fm + "\n" + line


def amount(s: str) -> float | None:
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except ValueError:
        return None


def comp_check(text: str, fm: str) -> tuple[str, str]:
    """Return (seen|not-found|unlisted, evidence line)."""
    targets = [v for v in (amount(field(fm, "comp_min")), amount(field(fm, "comp_max"))) if v]
    if field(fm, "comp_listed").lower() == "false" or not targets:
        return "unlisted", "note has no listed band"
    for m in DOLLAR.finditer(text):
        n = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        for t in targets:
            if abs(n - t) <= 500 or (n < 200 and abs(n * 2080 - t) <= 1500):
                a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
                return "seen", re.sub(r"\s+", " ", text[a:b]).strip()
    figures = sorted({m.group(0) for m in DOLLAR.finditer(text)})[:8]
    return "not-found", "page dollar figures: " + (", ".join(figures) or "none")


def capture(url: str, out: Path) -> str:
    """Load the page, expand it, save a full-page PNG; return the page text."""
    _ensure_patchright()
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--headless=new"])
        try:
            pg = b.new_context(user_agent=UA, viewport={"width": 1280, "height": 1000}).new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:  # noqa: BLE001  (SPAs long-poll; a timeout is normal)
                pass
            for el in pg.query_selector_all("button, a[role=button], [aria-expanded=false]"):
                try:
                    if EXPANDERS.match(el.inner_text() or "") and el.is_visible():
                        el.click(timeout=2000)
                except Exception:  # noqa: BLE001  (a stale or covered expander is skipped)
                    continue
            for _ in range(30):  # walk to the end so lazy sections render
                pg.mouse.wheel(0, 1500)
                pg.wait_for_timeout(250)
            pg.evaluate("window.scrollTo(0, 0)")
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(out), full_page=True)
            return pg.inner_text("body")
        finally:
            b.close()


def stamp(note: Path, txt: str, png: Path, comp: str, evidence: str, url: str) -> None:
    fm, end = frontmatter(txt)
    today = date.today().isoformat()
    fm = set_field(fm, "jd_snapshot", png.name)
    fm = set_field(fm, "jd_snapshot_date", today)
    fm = set_field(fm, "jd_snapshot_comp", comp)
    body = txt[end:]
    block = (f"> [!info]- Snapshot {today} (comp: {comp})\n"
             f"> Source: {url}\n> Comp check: {evidence}\n>\n> ![[{png.name}]]\n")
    if "## Listing snapshots" in body:
        body = body.replace("## Listing snapshots\n", "## Listing snapshots\n" + block + "\n", 1)
    else:
        section = "## Listing snapshots\n" + block + "\n"
        i = body.find("> [!info]- Raw JD")
        body = body[:i] + section + body[i:] if i >= 0 else body.rstrip("\n") + "\n\n" + section
    note.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Full-page screenshot of a job posting.")
    ap.add_argument("--note", required=True)
    ap.add_argument("--url", help="posting URL (default: from the note frontmatter)")
    ap.add_argument("--dry-run", action="store_true",
                    help="save to tmp/jd-snapshot, do not move or edit the note")
    a = ap.parse_args()

    note = Path(a.note).expanduser()
    txt = note.read_text(encoding="utf-8")
    fm, _ = frontmatter(txt)
    url = a.url or next((v for k in ("original_listing", "listing_url", "apply_url")
                         if (v := field(fm, k)).startswith("http")), "")
    if not url:
        print("NO URL: the note has no original_listing, listing_url or apply_url; pass --url.")
        return 2

    tmp = Path(__file__).resolve().parent.parent / "tmp/jd-snapshot"
    tmp.mkdir(parents=True, exist_ok=True)
    name = f"{note.stem} - posting {date.today().isoformat()}"
    shot = tmp / f"{name}.png"
    try:
        text = capture(url, shot)
    except Exception as e:  # noqa: BLE001  (report any load failure as nothing saved)
        print(f"NOT SAVED: {url}: {type(e).__name__}: {str(e)[:200]}")
        return 2

    comp, evidence = comp_check(text, fm)
    closed = CLOSED.search(text)
    print(f"comp   {comp}: {evidence}")
    if closed:
        print(f"CLOSED: page says \"{closed.group(0)}\". Note not moved; capture kept at {shot}")
        return 2
    if a.dry_run:
        print(f"saved  {shot}  (dry run, note untouched)")
        return 1 if comp == "not-found" else 0

    folder = note.parent
    if folder.name != note.stem:
        folder = note.parent / note.stem
        if (folder / note.name).exists():
            print(f"NOT SAVED: {folder / note.name} already exists; resolve the duplicate note.")
            return 2
        folder.mkdir(parents=True, exist_ok=True)
        note = note.rename(folder / note.name)
        print(f"moved  note into {folder}")
    png = folder / f"{name}.png"
    n = 2
    while png.exists():
        png = folder / f"{name} ({n}).png"
        n += 1
    shot.rename(png)
    print(f"saved  {png}  ({png.stat().st_size // 1024} KB)")
    stamp(note, txt, png, comp, evidence, url)
    print(f"note   {note.name}: frontmatter + Listing snapshots callout written")
    return 1 if comp == "not-found" else 0


if __name__ == "__main__":
    sys.exit(main())
