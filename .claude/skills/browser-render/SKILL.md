---
name: browser-render
description: Render HTML/SVG to a PNG/PDF image without flashing the screen. Canonical reference for headless-browser screenshots of local HTML files (rendering a generated page, character sheet, report, or canvas to an image to visually inspect it). Use whenever you would shell out to Chrome with --headless --screenshot, take a screenshot of an HTML file, render HTML to an image, or convert a local web page to PNG/PDF. AVOID raw `--headless=new` — it flashes the screen on macOS.
---

# Browser Render (flash-free HTML → image)

When you need to render a local HTML/SVG file to a PNG or PDF to inspect it (e.g. checking how a generated page, character sheet, or report looks), do NOT launch Chrome with `--headless=new`. On macOS that mode spins up a real GPU/window surface and produces a visible **white screen flash** on every launch. In a tight render→check→fix loop that strobes the whole display every few seconds and reads, to the user, like something is repeatedly taking a screenshot. (This was the cause of a real "my screen keeps flashing" report on 2026-06-03 — a render loop on the D&D character sheet.)

Important: the flash is purely cosmetic — headless Chrome screenshots a **file**, never the user's actual screen, so there is no privacy/capture concern. But it is alarming and unnecessary. Use a flash-free path.

## Preferred: `--headless=old`

One-flag change. The legacy headless mode renders fully offscreen (no window surface, no flash):

```bash
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=old --disable-gpu --no-first-run \
  --user-data-dir=/tmp/render-$$ --hide-scrollbars \
  --window-size=1000,1400 --screenshot=/tmp/out.png \
  "file:///tmp/page.html"
```

Verified to still produce a PNG on Chrome 148 (2026-06-03), even though old headless was nominally removed around Chrome 132 — the flag is still honored. **Caveat:** confirmed it *renders*; the no-flash behavior was not visually self-verified (can't see the screen from a tool). If you switch a loop to `--headless=old` and the user still reports flashing, Chrome is likely aliasing `old`→`new` on their version — fall back to Playwright below.

## Robust fallback: Playwright (best for JS-heavy pages)

If `--headless=old` still flashes, or the page needs real JS execution / interaction (clicking tabs, waiting on load), use Playwright's true-headless Chromium — it does not create an on-screen window on macOS:

```bash
# one-time: pip install playwright && playwright install chromium
python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()                 # headless by default, no flash
    pg = b.new_page(viewport={"width":1000,"height":1400})
    pg.goto("file:///tmp/page.html")
    pg.wait_for_load_state("networkidle")
    # pg.click('.ptab[data-page="spells"]')  # real interaction if needed
    pg.screenshot(path="/tmp/out.png", full_page=True)
    b.close()
PY
```

## PDF output (print-to-pdf)

For a PDF rather than a PNG, **default straight to Playwright's `page.pdf()`** — do not reach for Chrome's `--headless=old --print-to-pdf` first. On this machine that path hangs indefinitely and produces no file (it times out the Bash call and leaves a stuck Chrome + locked `--user-data-dir`). Playwright's `page.pdf()` renders in a second or two and, importantly, **preserves clickable links** — both external `https` URLs and internal `#anchor` jumps come through as live PDF link annotations, so numbered-citation dossiers (superscript markers that jump to a source list) work end to end.

```bash
python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("file:///tmp/page.html", wait_until="networkidle")
    pg.pdf(path="/path/out.pdf", format="Letter", print_background=True,
           margin={"top":"0.6in","bottom":"0.6in","left":"0.7in","right":"0.7in"})
    b.close()
PY
```

Use `@page { size: letter; margin: ... }` plus `-webkit-print-color-adjust: exact` in the HTML so background fills (callout boxes, header bands) actually print.

## Other options (static HTML only, no JS)

- `qlmanage -t -s 1400 -o /tmp "/tmp/page.html"` — macOS Quick Look, native, no flash, but ignores most JS.
- `wkhtmltoimage page.html out.png` — old WebKit, offscreen, no flash; weak JS. (`brew install --cask wkhtmltopdf`)

## Cleanup

Each Chrome render leaves a throwaway `--user-data-dir` and PNG in `/tmp`. Use a unique dir per call (e.g. `/tmp/render-$$`) and sweep stale ones afterward:

```bash
rm -rf /tmp/render-* /tmp/cs* /tmp/cnd*   # stale headless profiles
```

## Rule of thumb

Default to `--headless=old`. Reach for Playwright when the page is JS-driven or the flash persists. Never leave a raw `--headless=new` in a loop that runs while the user is at the machine.
