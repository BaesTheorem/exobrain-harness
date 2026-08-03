# promethease-md3

Material Design overhaul for [Promethease](https://promethease.com) reports.

Promethease hands you a single self-contained HTML file (10-30 MB, genome data
embedded) built on Bootstrap 3, jQuery UI and Chosen. It works, but it looks
like 2014 and buries the two numbers you actually scan for. This tool restyles
it and adds the missing navigation, without touching a byte of the report.

```
python3 apply.py ~/Downloads/promethease.html
open ~/Downloads/promethease.html
```

## How it works

The entire overhaul is one `<style>` + `<script>` block (`overlay.html`),
injected immediately before the closing `</body>`. Promethease's own markup,
data and JavaScript are left byte for byte alone.

That constraint is the whole design:

- Nothing can break the report's logic, because none of it is edited.
- Reverting is deleting the block, and it is byte-exact.
- Re-running replaces the block instead of stacking a second copy.
- Reports from a different Promethease version still work, because the overlay
  restyles by class and hooks the report's own render functions rather than
  rewriting its templates.

The overlay adds no network dependencies -- icons are inline SVG, and the type
falls back to the system sans if the report's Google Fonts link is unreachable.
It degrades better offline than the stock report does.

## Usage

```
apply.py report.html                 # in place; snapshots report.original.html
apply.py report.html -o themed.html  # write a copy instead
apply.py ~/Downloads/*.html          # several at once
apply.py report.html --check         # print status, change nothing
apply.py report.html --revert        # strip the overhaul back out
```

| Flag | Effect |
|------|--------|
| `-o, --output` | Write elsewhere instead of in place (single input only). |
| `--check` | Report version, whether it is a Promethease report, and size. |
| `--revert` | Remove the block; restores the original bytes exactly. |
| `--no-backup` | Skip the `.original.html` snapshot. |
| `--force` | Apply even if the file fails the Promethease sniff test. |

The `.original.html` snapshot is only written from a genuinely stock file, so
re-running never overwrites your real original with an already-themed copy.

Requires Python 3.9+ and nothing else.

## What the overhaul does

**Material Design 3**, in the flat/sharp variant -- square corners, hairline
borders, no shadows, elevation carried by surface tint.

- Full light and dark token sets, with a theme toggle in the app bar. Persists
  to `localStorage`, defaults to the OS setting. Chart.js pies and the Chartist
  population bars are recolored on switch so they stay legible in both.
- A real top app bar: full-width search with a leading icon and a clear button,
  MD3 underline tabs.
- Cards become surface containers with a repute-colored left rail. The filter
  panel becomes a navigation drawer with a heading and grouped sections.
- The third-party widgets are restyled too: jQuery UI sliders and tooltips,
  Chosen selects, Bootstrap modals and dropdowns, the intro.js tour.

**Navigation the stock report is missing.**

- **Status chips on every card** -- repute, magnitude with a 0-4 dot meter, and
  ClinVar significance -- lifted out of the stat table and deduped from it.
- **The stat table reads label then value**, instead of the original value then
  label.
- **Quick-filter chips with live counts**, driving the report's own filter
  state rather than a parallel one: magnitude thresholds, Good only, Bad only,
  ClinVar. Thresholds the report has no matches for are not rendered, so a
  report topping out at magnitude 4 shows three chips and one topping out at 10
  shows more.
- **A live count** ("10 of 56,569 shown") that updates on every filter change,
  and a real empty state instead of a blank page.
- **Compact cards** clamps long descriptions to about eleven lines behind a
  Show more control, and only on cards actually measured as overflowing.
- `/` focuses search, `Esc` clears it. "2x more" becomes "Show more results"
  with the number of remaining matches.
- Broken SNPedia thumbnails are hidden. Many reports ship them as base64
  error pages rather than images.

**Two stock bugs fixed along the way.**

- Below about 1200px the filter drawer covered the card list, because
  Promethease puts the tab panel outside the element its offcanvas drawer
  pushes. The content now measures and reserves the overlap.
- Printing forced one page per variant at a fixed 216x279mm. It is now a normal
  flow with cards avoiding page breaks.

## Files

| File | Purpose |
|------|---------|
| `apply.py` | CLI. Inject, check, revert. |
| `overlay.html` | The injected block. Version stamped in the `BEGIN` marker. |

## Scope

This is Promethease-specific -- it keys on `#genoslist`, `.boxresult` and the
repute classes. It is not a generic "genetic report" themer, and `apply.py`
refuses files that fail the sniff test unless you pass `--force`.

For a different vendor's report format, the pattern still holds (append an
overlay, restyle by class, hook the render functions), but the selectors in
`overlay.html` would need rewriting against that report's DOM.

## Privacy

Reports contain your genome. Keep them out of this repo -- run the tool against
files wherever they already live (`~/Downloads`, an encrypted volume). Nothing
here reads, transmits or stores report contents; `apply.py` only rewrites the
file you point it at, on disk, locally.
