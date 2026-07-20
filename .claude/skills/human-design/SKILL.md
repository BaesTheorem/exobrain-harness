---
name: human-design
description: Generate professional printable Human Design PDF packets (BodyGraph, Type, Strategy, Authority, Profile, Definition, Incarnation Cross) from birth data, using the human-design pipeline repo. Use when the user asks for a Human Design chart, BodyGraph, HD reading, "what's my type", Projector/Generator/Manifestor/Reflector, "run my human design", or wants an HD packet for someone. Handles compute, interpretation writing, de-AI pass, PDF render, and visual verification.
---

# Human Design Packets

Produces print-ready Letter PDF packets, one per person: a themed BodyGraph, the full
Design/Personality activation table, Type / Strategy / Authority / Profile / Definition /
Incarnation Cross, and plain-language interpretation. All astronomy runs on the Swiss
Ephemeris (Design taken at 88° of solar arc before birth; gates on the Rave Mandala
anchored at Gate 41 = 302°; true node). Prose is written fresh per person.

This is the sibling of `/birth-chart` (astrology). Same shape, same de-AI discipline,
its own repo. If the user wants BOTH an astrology chart and a Human Design chart, run each
skill; keep the deliverables separate.

**Repo**: `~/Documents/human-design` (public: `BaesTheorem/human-design`). Real people's
data lives only under `work/` (gitignored). Read the repo's `pipeline/content_guide.md`
and `pipeline/reference.md` before writing any prose; the guide is the canonical contract.

## Inputs to collect

Per person: name (or preferred label), date, **exact birth time**, birthplace. Convert to
decimal lat/lng and an IANA tz string yourself; don't ask for coordinates if the city is
unambiguous. Birth time matters a lot: the Moon changes gate every ~4-5 hours and the
Sun's line every ~22 hours, so an unknown or rounded time can flip the Profile, Authority,
or even the Type. If the time is unknown, say so plainly and tell the user which properties
are unreliable; offer to compute anyway with that caveat, but do not present a
time-sensitive packet as authoritative.

## Workflow

1. **Work dir**: `mkdir work/<slug>` in the repo; write `subjects.yaml` (copy
   `subjects.example.yaml`; add `connection: [slug-a, slug-b]` only when a two-person
   connection packet is wanted).
2. **Compute**: `.venv/bin/python make.py work/<dir>`. First run computes the chart(s),
   writes `chart-data.json` and `bodygraph-<slug>.svg`, prints the headline vitals, then
   stops and lists the content modules still needed. Inspect `chart-data.json` before
   writing a word.
3. **Sanity-check the compute**: the printed Type/Authority/Profile/Definition/Cross should
   be internally consistent (e.g. Emotional authority ⇒ Solar Plexus defined; Projector ⇒
   no Sacral and no motor-to-Throat). If something looks off, re-check the birth time/tz
   before proceeding. `pipeline/validate.py` reproduces a known-correct published chart if
   you want to confirm the engine end-to-end.
4. **Write content modules**: copy `pipeline/content_template.py` to
   `work/<dir>/content_<slug>.py` and write each section. Ground every claim in this
   person's computed chart: the actual Type wiring, the specific gates/channels/lines, the
   open vs defined centers. Draw keynotes from `reference.md` but never paste them. Lead
   with Type + Strategy + Authority (the load-bearing core); give open centers real space
   (gifts, not deficits); stay honest, never fatalistic.
5. **De-AI pass (mandatory, before rendering)**: run the `/de-ai` checklist over all prose.
   Minimum greps: em dashes, metaphorical "quietly" and hype adverbs, correctio ("is not X;
   it is Y"), "genuinely/precisely/profound/remarkable", repeated openers, stacked
   three-item lists, reference.md keynotes pasted verbatim, and interpretive sentences
   copy-pasted between packets.
6. **Render**: `.venv/bin/python make.py work/<dir> --dest ~/Downloads/"Human Design"`.
7. **Verify visually**: Read the PDF (cover, one table page, one prose page). Check: cover
   fits one page, the BodyGraph renders with the right centers filled (defined) vs white
   (open) and channels drawn, glyphs render as text not emoji (the build forces U+FE0E),
   tables not orphaned, the activation table matches `chart-data.json`. Fix and re-render
   until clean.
8. Tell the user where the PDF landed, with the page count and the headline: Type,
   Strategy, Authority, Profile, Definition, Incarnation Cross.

## Gotchas learned the hard way

- **The engine is validated against a published chart** (`pipeline/validate.py`, the
  aHumanDesign.com reference for a 1994 birth). It reproduces all 26 activations and every
  derived property. If you change `hd.py` or `compute.py`, re-run validate.py before
  trusting output.
- **True node, not mean.** Mean node misses the node lines by a hair and disagrees with
  published charts. `compute.py` uses `swe.TRUE_NODE`; don't change it.
- **Design date isn't "88 days" flat.** It's the moment the Sun was exactly 88° of
  longitude earlier, solved by iteration. The screenshot's "Design Date" should match
  `design_utc` in the data.
- **Incarnation Cross names** live in `pipeline/crosses.json`. If a cross isn't in the
  table, the packet shows the gates + angle and omits the name; don't invent a name.
- **Gate keynotes drift between HD schools.** `reference.md` flags this. Spot-check the
  specific person's active gate keynotes and their exact cross name against Jovian Archive
  before delivery.
- **The Variables layer (Digestion/Sense/Environment/Motivation/Perspective + the four
  arrows) is the most birth-time-sensitive part of the chart** (a Tone shifts ~40 min, a
  Color ~4 hr). It comes from `subj["variables"]` (computed in `pipeline/variables.py` from
  color/tone). Only present it with an exact birth time, and flag the caveat in the packet.
  If the time is rounded/unknown, say the Variables are unreliable or omit the section.
- PDF via Playwright `page.pdf()` only (see `/browser-render`).
- Never commit anything under `work/`: names, birth data, and readings are personal.

## Privacy

Birth data is personal data. It stays in `work/` (gitignored) and in the delivered PDFs.
Do not copy names or birth details into the harness repo, session memories included; refer
to packets by slug if needed.
