---
name: geoguesser
description: "Geolocate a photo or play GeoGuessr at a competitive level -- read an image down to a country and then a region from bollards, road lines, camera generation, script, vegetation and sun angle, and back the read with real tools (shadow-to-latitude solver, Street View coverage lookup, Overpass, scoring math). Use when Alex says geoguessr, geoguesser, geoguess, 'where is this', 'where was this taken', 'guess the location', 'play geoguessr', pastes a street-level or landscape photo and asks to place it, asks about bollards/road-line/camera meta, or wants to locate something from a picture."
metadata:
  tools: "geoguessr/bin/geo in the Exobrain harness repo"
  references: "references/ in this skill dir -- seven files, load only what the round needs"
---

# /geoguesser

Two jobs share this skill: **playing GeoGuessr** (a screenshot, a guess, a score) and
**geolocating a real photo** (OSINT-style, no score, higher standard of proof). The
reading procedure is the same. What differs is the stopping rule, covered at the end.

You have a real advantage here and a real weakness. The advantage is that you see the
whole frame at once and hold every country's meta simultaneously, which no human does.
The weakness is that you will confabulate a confident country from a vibe if you let
yourself, and a vibe is unfalsifiable. So the discipline below is not ceremony: it is the
thing that separates a 4700 from a plausible-sounding 1200.

## The core loop

**Name the evidence before you name the country.** Write down what you actually see, then
ask which countries that set is consistent with. Not the reverse. The failure mode is
picking a country in the first two seconds and then reading each subsequent clue as
confirmation.

Then, for every candidate: **what else would this predict?** If it is Poland, there should
be white road lines, often doubled, a red-band bollard, and a holey concrete pole. Go look
for those specific things. The high-value observation is the one where your top two
candidates *disagree*, not the one they'd both pass.

## Scan order

Run this top to bottom. It is ordered by information-per-second, and it is roughly what
Plonk It teaches as the progression from general to specific.

1. **Driving side.** Free, instant, halves the world. Read it from parked cars, the
   centre line's position relative to the car, oncoming traffic, or the driver's seat.
2. **Script and language.** Any text at all. See `references/text-and-language.md`. This
   is usually the single fastest country-level answer when text exists.
3. **Camera generation and the Google car.** Resolution, sky halo, the blur at the bottom
   of frame, a visible roof rack or snorkel or antenna. Several countries are a one-look
   ID from the rig alone. See `references/camera-and-car.md`.
4. **Road infrastructure.** Bollards first (the highest-yield single clue in the game),
   then road-line colour and pattern, then utility poles, guardrails, signs, plates. See
   `references/infrastructure.md`. Almost every round is on a road, so this category pays
   more reliably than anything else.
5. **Landscape.** Vegetation, soil colour, terrain, climate band, season. See
   `references/nature-and-sun.md`. Slower and fuzzier, but it is what carries a round
   with no text and no infrastructure.
6. **Sun and shadows.** Hemisphere, then latitude. Qualitative first (shadow pointing
   north at midday means northern hemisphere); quantitative via `geo sun` when it matters.
7. **Brands and commercial signage.** Gas stations, telecom, beer, retail. See
   `references/brands.md`. Strong when the brand is genuinely single-country, worthless
   when it is Shell.
8. **Regionguessing.** Once the country is fixed, go down a level: plate codes, road
   number prefixes, phone area codes, prefecture or state markers. See
   `references/regionguessing.md`. On a country-locked map this is where all the points
   are.

Do not run all eight when three have already converged. Gate each step on "would the
answer change what I guess?"

## Scoring, and what precision is actually worth

`geo score` prints the curve. The formula is `5000 * exp(-10 * d / D)` where `D` is the
map's bounding-box diagonal; the World map behaves as if `D` is about 15,000 km.

On the World map that means:

| miss | points |
|---|---|
| 30 km | 4900 |
| 158 km | 4500 |
| 335 km | 4000 |
| 766 km | 3000 |
| 2414 km | 1000 |

The curve is flat far out and steep close in. Two consequences that should drive every
decision:

- **Country is nearly everything.** Being on the wrong continent costs thousands. Being in
  the wrong *half* of a correct mid-sized country costs a few hundred. Spend your time
  resolving the country and stop grinding for the exact town on a world map.
- **On a country-locked map the reverse holds.** `D` is small, so 100 km is catastrophic
  and regionguessing is the entire game. Pass `--map-diagonal` to `geo score` to see it.

**When you are not sure, hedge.** Guess the centre of the region you believe it is in, not
the most likely single point. If it is Spain-or-Portugal, plonk the border, not Madrid.
The community calls a guess in the water between two candidate landmasses a "water hedge"
and it is correct play, not cowardice. Minimising expected loss beats maximising the best
case, because the curve punishes distance and does not reward bravery.

Also weight by **coverage density, not area**. Population and roads cluster; a random
Street View point in Russia is far more likely to be west of the Urals than in Sakha.

## The tools

`geoguessr/bin/geo` is in this repo. Everything in it is deterministic; it exists so the
parts with a rule stop being guesswork. Full catalog of what else is out there, including
what is NOT worth installing, in `references/tools.md`.

```
geo sun --height 1 --shadow 1.4 --shadow-azimuth 20 [--date 2026-07-15]
```
Latitude from a shadow. Give the object's height, its shadow's length in the same units,
and the compass bearing the shadow points. With `--date` you get a latitude and the local
solar time; without one it sweeps the year and gives a band. It returns **every** latitude
that fits, including both branches, and returns nothing at all when the geometry is
impossible. Verified by round-trip tests in `tests/test_geo_solver.py`.

Caveats that matter: it assumes flat ground and a vertical object, and it is sensitive.
An 8% error in the shadow ratio plus 4 degrees of bearing error moved a test case by 5
degrees of latitude. Treat the output as a band, and re-measure rather than trusting one
reading. Shadow *direction* stays useful all day; shadow *length* degrades badly more
than about three hours from solar noon.

```
geo sunpos <lat> <lon> --date 2026-03-15 --solar-time 15
```
The forward check. Given a candidate location, what should the shadow look like? Run this
against your guess and compare to the image. Disagreement kills the guess.

```
geo pano <lat> <lon> [--radius 500]
```
Is there Street View here, and from when. Keyless, via `streetlevel`. Returns the pano ID,
exact coordinates, capture month, country code, address and car heading, or tells you
there is no coverage. Use it to (a) sanity-check that a candidate could even be a round,
and (b) match the capture date against the camera generation you think you are seeing.
First run downloads a Python 3.12 environment, so it takes a few seconds; later runs are
fast.

```
geo score [--km 400] [--points 4500] [--guess lat,lon --answer lat,lon] [--map-diagonal 1500]
```
Scoring both directions, plus the distance between two points.

```
geo geocode "Wadowice" --country pl
geo where <lat> <lon>
```
A place name read off a sign to coordinates, and a candidate coordinate back to a country
and region. Always run `geo where` on a final answer before committing to a country claim
in prose: it is a two-second check that catches a guess that landed in the wrong country.

```
geo elev 39.41411,-105.75770 39.39140,-105.79054
```
Ground elevation at any number of points, batched, no key. This is what turns a "looks
high above the valley" impression into a number, and it is how you falsify a candidate
viewpoint: work out the drop to a landmark, compare it against the landmark's depression
in frame, and see whether the implied field of view is one a real camera has.

```
geo overpass '<Overpass QL>'
```
Narrow from partial clues. `[out:json]` is added automatically. This is how you turn "a
village called Zalesie with a church, in Poland" into a candidate list. Be warned that it
answers honestly: there are 97 villages named Zalesie in Poland, which is the point.

```
geo enhance shot.png --crop 400x200+1100+640 --scale 4
```
Crop and upscale a region so a blurry sign becomes readable, then look at the output. This
is the single highest-leverage tool you have, because your own vision is better than any
OCR here and the only thing stopping you is pixel size. Reach for it before guessing at a
half-legible word. (Do not bother with `exiftool` on a game screenshot: there is no source
camera, so there is no GPS EXIF. On a photo Alex was actually sent, check it first.)

## Epistemics

**Confidence is part of the answer.** Say "Poland, 80%, with Czechia the live alternative"
rather than "Poland." A stated alternative is what makes the claim checkable, and Alex can
act on a calibrated 60% but not on a fake 100%.

**Fake metas are real.** Some widely repeated clues are only statistical. Indonesian
pole-tops genuinely regionguess, and genuinely show up where they should not. "Kyrgyzstan
has a red car" is simply out of date (it is a white car with a roof rack now). Estonian
white flowers are Baltic-wide. Treat a fake meta as evidence that shifts a prior, never as
a confirmation that ends the search. `references/brands.md` has the list.

**Coverage season is a trap.** Some low-coverage countries were shot almost entirely in
one season, so the "feel" you build for them is an artifact of when Google drove, not what
the country looks like.

**Do not trust a single clue that contradicts three others.** Notice the confusion instead
of explaining it away. If everything says Brazil and one sign says Portuguese Portugal,
you have probably misread the sign, or you have found a genuinely diagnostic anomaly. Go
check which, do not average them.

**Never assert a location you have not checked.** If you name coordinates, run `geo where`
or `geo pano` on them first. If you name a capture date or a camera generation, say which
you observed rather than which you inferred.

## Stopping rules

**Playing GeoGuessr:** stop when the next observation would not change the guess, or when
the clock forces it. Commit to the hedge. There is no credit for an unplaced answer.

**Geolocating a real photo for Alex:** the standard is higher and there is no clock. Do
not stop at a country if the image supports a town. Confirm the final candidate with
`geo pano` and a reverse geocode, and state plainly what is verified versus inferred. If
you get to a region but not a point, say so; a wrong specific answer is worse than a right
vague one.

## Getting better over time

After a miss, go back to the round and cross-reference what was actually there against
the reference files. That habit is what the community identifies as the single biggest
driver of improvement, and it is the one that transfers to you: when a reference file is
wrong or thin, **fix the file**. These references are the persistent memory for this
skill; a lesson that stays in a chat is lost.

Study sources, in order of usefulness: `plonkit.net` (canonical, per-country, organised
country-ID then regionguessing), `geohints.com` (raw exhaustive database, use when you
know what you are looking for), `learnablemeta.com`, `geotips.net`. Plonk It is a JS SPA
that blocks plain scrapers; its content comes out of the embedded `__PRELOADED_DATA__`
JSON in the page HTML. GeoHints sits behind Cloudflare and often needs the Wayback
Machine, though `curl` on its `/meta/*` pages worked directly.

## Reference files

Load only what the round needs. They are large and mostly independent.

| file | contents |
|---|---|
| `references/infrastructure.md` | bollards, road lines, utility poles, guardrails, signs, licence plates, crossings |
| `references/camera-and-car.md` | camera generations, car and blur meta, coverage by country, capture dates |
| `references/text-and-language.md` | scripts, diacritics, Cyrillic variants, TLDs, phone formats, currency, road typefaces |
| `references/nature-and-sun.md` | vegetation, soil, climate bands, terrain, and the solar math with worked examples |
| `references/brands.md` | gas stations, beer, telecom, retail, plus the fake-meta list |
| `references/regionguessing.md` | subnational tells and code tables for the US, Russia, Brazil, Japan, India and more |
| `references/tools.md` | the wider tool and model landscape, what works, what is not worth it |
