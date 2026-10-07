---
name: backpacking
description: Plan a backpacking or overnight hiking trip and ship it as a shareable plan. Research trails and conditions, design the route around water and legal camps, measure miles and elevation, check land ownership, upload the route to AllTrails, and publish an interactive map page (unlisted, on the personal site) in the TheTrail style. Use when Alex says "/backpacking", "plan a backpacking trip", "plan an overnight hike", "where should we camp", "how far each day", "make a trip plan", "trip page", "map this route", "put this route on AllTrails", "share the trip with my friends", or asks to compare trails for a 1 to 4 night trip.
---

# Backpacking

The tool is `backpacking/` in the harness. Read `backpacking/README.md` for the commands and the `trip.json` format. Commands run from the harness root. The first trip built with it: `backpacking/trips/cedar-creek-smith-backbone/`. Copy that config when you start a new trip.

## 1. Brainstorm before you build

When the brief is open ("a 1-night trip, 8 to 12 miles"), give Alex three to five candidates first, with a recommendation, and build only the one he picks. For each candidate, say which numbers you measured and which are leads you have not checked.

## 2. Research rules

- **AllTrails is a starting point only.** It is crowd-sourced. Use `alltrails/bin/alltrails` (search, trail, reviews, gpx, weather) to find candidates and dated condition reports. Confirm every number the plan depends on with the land manager. When the two disagree, the land manager wins. See memory `feedback_alltrails_starting_point_only`.
- **Land manager pages** (USFS, NPS, state parks, MDC) for trail lengths, campgrounds, fees, seasons, water, closures and alerts. Use WebFetch, or off-screen Chrome when a page blocks plain HTTP.
- **Named landforms** (ridges, bluffs, falls): use the USGS GNIS state text file, not a guess from a map. See memory `reference_gnis_named_landforms`. For overlooks, use OSM `tourism=viewpoint` nodes.
- **Hunting seasons** from the state wildlife agency, for the dates of the trip.
- **A WebSearch summary is never evidence.** Open the source page and quote it.
- If a position comes from a scanned map and not from a GPS source, mark the waypoint `approx` and say so on the page.

## 3. Route design rules

1. **Water decides the route.** List the taps first. Then use the NHD perennial streams, and check recent reports for dry crossings. Put every night next to the most reliable water.
2. **Every camp must be on public land where dispersed camping is allowed.** Run `trip check`. On 2026-10-06, Rutherford Bridge, the obvious camp, turned out to be on private land 360 ft from the forest boundary. Never call a place "camp" before this check passes.
3. **Side trips go out and back from camp with day packs.** This keeps the full-pack miles low. Mark them `side: true`, so they draw dotted and get tagged.
4. **Cut road and pasture miles** when the land manager or trip reports describe a section that way.
5. **Measure repeated trail** between days, and say the number on the page. Do not claim "no trail twice" without measuring it.
6. Each tab shows only its own milestones, side-trip tags and rationale entries (`plans` on each `why` entry).

## 4. Pipeline

```
backpacking/bin/trip build      backpacking/trips/<slug>     # route, elevation, land, camp check, page
backpacking/bin/trip shots      backpacking/trips/<slug>     # look at build/shots/*.png, fix, repeat
backpacking/bin/trip alltrails  backpacking/trips/<slug>     # AllTrails custom route (public, so it can be shared)
backpacking/bin/trip web        backpacking/trips/<slug>     # again, to pick up the AllTrails link
backpacking/bin/trip publish    backpacking/trips/<slug>     # unlisted page, waits until it is live
```

- Do not wrap these commands in `mist-progress run`. Its pty swallows their output. One AllTrails upload was lost that way.
- Read every screenshot (desktop, each tab, the rationale, the phone) before you publish. `shots` fails on any JS error.
- `alltrails --replace` deletes this trip's old AllTrails maps before it uploads again. The share links then change, so tell Alex.

## 5. Design aesthetic

- The look is **TheTrail hiking dashboard by RonDesignLab** (dribbble.com/shots/26489961), which Alex picked: Outfit type, `#012FFF` blue, `#E1FF4F` lime, grey neutrals, translucent cards, big thin numerals, dot chips, and USGS satellite imagery.
- **Never use the cream and rust Instrument Serif look.** Alex rejected it on 2026-10-06 because it reads as AI.
- **Map rules learned from Alex's feedback:**
  - Show imagery everywhere. Private land gets only a 20% tint, and Forest Service parcels get a thin outline. A mask that cuts the map to the parcels looks half rendered.
  - No relief tile layer. Its blend in Leaflet came out as a grey film plus tile seams.
  - Tap water is a blue dot at the waypoint. The main creek is a thin blue line with italic labels.
  - Camps have a black tent marker, and side trips are dotted lime with a "Side trip" tag.
- Use the stock Material Symbols Outlined icons. The page loads only the icons it uses.
- For a new kind of artifact, find a reference on dribbble.com or awwwards.com first, and show it to Alex before you build.

## 6. Sharing

- The page publishes to `becomingstronger.github.io/trips/<slug>-<10-char token>/`. It has `noindex`, nothing on the site links to it, and it has an og.jpg preview for link cards. The site repo is public, so "unlisted" hides the page from search and from the site, not from someone who browses the repo. Tell Alex this the first time.
- Embed any PDF in the Console as `![name](/abs/path.pdf)`. See memory `feedback_console_pdf_embed`.
- Give Alex the live link, the AllTrails link, and a short list of what the checks found, for example "the camp at X is on private land, so I moved it".
