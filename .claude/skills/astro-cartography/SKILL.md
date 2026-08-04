---
name: astro-cartography
description: Generate professional printable astrocartography PDF packets (planetary lines on world maps, city sweeps, relocated angles) from birth data, using the astro-cartography pipeline repo. Use when the user asks for astrocartography, an astro-cartography map, relocation astrology, "where should I live", planetary lines, a Venus/Saturn line lookup, or wants a relocation packet for someone. Handles compute, interpretation writing, de-AI pass, PDF render, and visual verification.
---

# Astrocartography Packets

Produces print-ready Letter PDF packets, one per person: a themed world map of the ten
planets' MC/IC/AC/DC lines, optional regional zoom maps, the line atlas table, a
world-city sweep of every line contact inside a 750 km orb, relocated angles for chosen
places, and plain-language interpretation. Lines are in mundo (the Jim Lewis standard),
computed on the Swiss Ephemeris from apparent RA/declination and apparent sidereal time.

Sibling of `/birth-chart` and `/human-design`: same shape (compute, hand-written prose
modules, de-AI, Playwright PDF), its own repo and its own spruce-and-copper theme. If the
user wants multiple packet types, run each skill; keep the deliverables separate.

**Repo**: `~/Documents/astro-cartography` (public: `BaesTheorem/astro-cartography`). Real
people's data lives only under `work/` (gitignored). Read the repo's
`pipeline/content_guide.md` before writing any prose; it is the canonical contract.

## Inputs to collect

Per person: name (or preferred label), date, exact birth time, birthplace. Convert to
decimal lat/lng and an IANA tz string yourself. Also ask two things the siblings don't
need: **which places matter** (where they live, where they're considering; goes in
`places:` for relocated angles and nearest-lines tables) and **which regions deserve zoom
maps** (`regions:` from north-america, south-america, europe, africa, asia, oceania).
Birth time sensitivity: the whole map shifts ~15° of longitude per hour of clock error, so
a rounded time slides every line by real distance (~1° lon per 4 min). If the time is
unknown, say plainly that line positions carry that uncertainty; don't present a packet
from a guessed time as authoritative.

## Workflow

1. **Work dir**: `mkdir work/<slug>` in the repo; write `subjects.yaml` (copy
   `subjects.example.yaml`; add `places:` and `regions:`).
2. **Compute**: `.venv/bin/python make.py work/<dir>`. Prints the top city hits and stops,
   listing the content modules still needed. Inspect `chart-data.json` (planets, lines,
   city_hits, places) before writing a word.
3. **Write content modules**: copy `pipeline/content_template.py` to
   `work/<dir>/content_<slug>.py`. Ground every claim in the computed data: name the line,
   the city, the km from `hits_for`. Cover strip = the three most load-bearing lines.
   Part Four weighs each focus place honestly (cost as well as pull); Saturn/Pluto lines
   honest, not doom; no promise that a move fixes anything.
4. **De-AI pass (mandatory, before rendering)**: run the `/de-ai` checklist over all
   prose. Minimum greps: em dashes, metaphorical "quietly" and hype adverbs, correctio,
   "genuinely/precisely/profound/remarkable", repeated openers ("Under this line"),
   stacked three-item lists, interpretive sentences copy-pasted between packets.
5. **Render**: `.venv/bin/python make.py work/<dir> --dest ~/Downloads/"Astrocartography"`.
6. **Verify visually**: Read the PDF (cover, line atlas page, city table, one prose page).
   Check: cover fits one page with map + legend, lines loop correctly (AC/DC curves
   converge onto the MC/IC meridians at high latitudes), map labels legible, glyphs render
   as text not emoji, tables not orphaned. Fix and re-render until clean.
7. Tell the user where the PDF landed, page count, and the headline: strongest three
   lines and the verdicts on their focus places.

## Gotchas learned the hard way

- **The engine is validated** (`pipeline/validate.py`): swe.azalt must see zero true
  altitude along every horizon curve and swe.houses must reproduce the Sun's longitude as
  relocated ASC/MC on the Sun lines, with negative controls. If you touch `astro.py`,
  re-run it before trusting output.
- **In mundo vs in zodiaco**: for planets with ecliptic latitude (the Moon especially),
  being on the horizon is NOT the same as conjoining the relocated Ascendant in zodiac
  longitude. The maps are in mundo; don't "verify" a Moon line against a relocated chart's
  ASC degree and conclude the engine is broken.
- **Each map SVG carries a unique clipPath id** (`frame-<region>`); several maps get
  inlined into one HTML document and duplicate ids make every map clip to the first one's
  frame. Keep the pattern if adding new SVG assets.
- **Ephemeris files are enforced**: compute refuses to run without `ephe/*.se1`
  (`python pipeline/ephemeris.py --fetch` once per clone).
- **Playwright chromium is per-venv**: fresh clone needs
  `.venv/bin/playwright install chromium`.
- The city gazetteer is hand-curated to 0.1° (~11 km); quote distances as computed, don't
  re-derive. A city can legitimately appear on several lines.
- PDF via Playwright `page.pdf()` only (Chrome `--headless=old` hangs on this machine; see
  `/browser-render`).
- Never commit anything under `work/`: names, birth data, and readings are personal.

## Privacy

Birth data is personal data. It stays in `work/` (gitignored) and in the delivered PDFs.
Do not copy names or birth details into the harness repo, session memories included; refer
to packets by slug if needed.
