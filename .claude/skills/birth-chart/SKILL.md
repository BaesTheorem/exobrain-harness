---
name: birth-chart
description: Generate professional printable birth-chart PDF packets (natal and synastry) from birth data, using the birth-charts pipeline repo. Use when the user asks for a birth chart, natal chart, zodiac chart, astrology reading, synastry or compatibility chart, "do our charts", or wants a chart packet for someone. Handles compute, interpretation writing, de-AI pass, PDF render, and visual verification.
---

# Birth Chart Packets

Produces print-ready Letter PDF packets: one natal packet per person, plus a synastry
packet when two people are given. All astronomy runs on the Swiss Ephemeris (tropical
zodiac, Placidus houses); prose is written fresh per person.

**Repo**: `~/Documents/birth-charts` (public: `BaesTheorem/birth-charts`). Real people's
data lives only under `work/` (gitignored). Read the repo's
`pipeline/content_guide.md` before writing any prose; it is the canonical contract.

## Inputs to collect

Per person: name (or preferred label), date, exact birth time, birthplace. Convert to
decimal lat/lng and an IANA tz string yourself; do not ask the user for coordinates if
the city is unambiguous. If birth time is unknown, warn that houses/Ascendant are
unreliable and offer a solar chart instead (noon, and skip house-based claims).

## Workflow

1. **Work dir**: `mkdir work/<slug-pair>` in the repo; write `subjects.yaml` (copy
   `subjects.example.yaml` shape; `synastry: [slug-a, slug-b]` only when a pair packet
   is wanted).
2. **Compute**: `.venv/bin/python make.py work/<dir>`. First run prints which content
   modules are missing and exits. Inspect `chart-data.json` (or the compute stdout) for
   the placements before writing a word.
3. **Write content modules**: copy `pipeline/content_template.py` per subject, plus a
   synastry module (crib the section list from `pipeline/content_guide.md`). Every
   claim must be grounded in the computed data: placement, house, orb. Plain language,
   honest about hard aspects, no doom and no flattery.
4. **De-AI pass (mandatory, before rendering)**: run the `/de-ai` skill checklist over
   all prose. Minimum greps: em dashes, metaphorical "quietly" and hype adverbs,
   correctio ("is not X; it is Y"), "genuinely/precisely/profound/remarkable",
   repeated openers ("This is a person who"), stacked three-item lists, interpretive
   sentences copy-pasted between packets.
5. **Render**: `.venv/bin/python make.py work/<dir> --dest ~/Downloads/"Birth Charts"`.
6. **Verify visually**: Read the PDFs (cover page, one table page, one prose page per
   packet). Check: cover fits one page, glyphs render as text not emoji (the build
   forces U+FE0E; if emoji appear, the post-processor broke), tables not orphaned,
   wheel legible. Fix and re-render until clean.
7. Tell the user where the PDFs landed, with page counts and the headline findings.

## Gotchas learned the hard way

- Kerykeion v5: pass `online=False` with explicit `lng/lat/tz_str`;
  `RelationshipScoreFactory` needs `.model()` objects, not raw subjects.
- The elegant wheel theme is `theme/elegant.css`, swapped into the SVG's
  `Theme_Colors_Tag` style block by `compute.py`. Adjust colors there, never in the
  generated SVGs.
- PDF via Playwright `page.pdf()` only (Chrome `--headless=old --print-to-pdf` hangs on
  this machine; see `/browser-render`).
- In synastry aspect data, p1 belongs to the first slug in the `synastry:` pair. Get
  this wrong and every "his X aspects her Y" sentence is backwards.
- Never commit anything under `work/`: names, birth data, and readings are personal.

## Privacy

Birth data is personal data. It stays in `work/` (gitignored) and in the delivered
PDFs. Do not copy names or birth details into this harness repo, session memories
included; refer to packets by slug if needed.
