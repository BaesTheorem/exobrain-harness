# Camera meta, car meta, and coverage

Identifying a country from the capture rig rather than the landscape. Gated as
intermediate-level in the community's own teaching order: learn infrastructure and
landscape first, because this category is memorisation of quirks rather than durable
geography. But it is fast when it fires.

Primary sources: geohints.com (`/meta/cameraGens`, `/meta/countries`, and the Cars, Boats,
Snowmobiles and Follow-Cars pages), geodummy.com, and Wikipedia's "Coverage of Google
Street View". GeoHints sits behind Cloudflare; the `/meta/*` pages answer plain `curl`,
older pages may need the Wayback Machine.

---

## Camera generations

| Gen | How it looks |
|---|---|
| **Gen 1** | Very low resolution, heavy compression, washed-out muted colours, no sky halo |
| **Gen 2** | The **halo**: a bright circular lens-flare distortion around the sun when panning up. Nadir (straight down) often shows a **purple/magenta circular blur** at the stitching seam. Low resolution, colours can be oversaturated |
| **Gen 3** | No halo, clean sky, sharper text, smaller and less colourful nadir blur, a visible car-shaped blur at the bottom. The modern baseline covering most of the world |
| **Gen 4** | Highest resolution, most vibrant and accurate colour, near-seamless stitching, small-to-absent nadir blur (sometimes just a clean copyright logo). The car blur usually has a blue tint |

**Corrections to two things people repeat.** There is no documented "yellowish tint" for
Gen 2 anywhere; the documented tint is purple/magenta. And no source, including geohints
itself, uses the term "Gen 2.5" or defines it. Do not assert either.

GeoHints' 2025 data adds two categories it labels but does not define in prose: **"Bad
Cam"** and **"Small Cam"**. Treat them as real labels with unknown definitions rather than
mapping them onto a "Gen 2.5" idea.

**Low Cam** — camera mounted lower on the car as a privacy modification. Bigger,
non-circular car blur, no sky blur. Countries: Austria, France, Germany, Italy, Japan,
Lebanon, Liechtenstein, Sri Lanka, Switzerland. Plonk It notes that Japan, Switzerland and
Liechtenstein use it *exclusively*, which makes it a very strong tell there. Taiwan often
has a wide blur but is **not** low-mounted; do not confuse them. Plonk It also warns that
Gen 2's circular top-and-bottom blur gets mistaken for Low Cam, and that steep inclines
fake either look.

**Trekker** — backpack-mounted, no car, sub-categorised by the generation of camera the
backpack carried.

### Near-instant generation IDs

Countries whose entire base coverage never got past Gen 2:

- **Jersey** — Gen 2 only
- **Macao** — Gen 2 only
- **Isle of Man** — Gen 2 base, supplemented only by a Trekker Gen 3 patch
- **Iraq** — the only official coverage is Trekker (Gen 2); no car coverage exists

Gen 1 survives only as scattered legacy patches, never dominant, in: Australia, Canada,
France, Italy, Japan, Mexico, Monaco, New Zealand, USA. Seeing Gen 1 narrows to that list
but is not a single-country lock.

**Gen 4 only** (recent first-time or renewed capture): Rwanda, Kazakhstan, Oman, Nicaragua,
Namibia, Panama, Gambia, Georgia. Wikipedia confirms Rwanda explicitly as the "first
country with 4th generation coverage only" — combined with African context that is close
to a one-look ID.

**Croatia** splits cleanly: Google returned in 2022 after an 11-year hiatus, so coverage is
either pre-2011 (Gen 2/3) or 2022+ (Gen 4), with nothing between.

---

## Car meta

### The near-certain tells

| Country | Car |
|---|---|
| **Kenya** | Black SUV with a massive black **snorkel** on the front-right fender. Careful: older Gen 3 Kenya coverage instead shows a hood mirror on the *left* |
| **Ghana** | Silver roof rack held together with **black duct tape** on the front bars. Réunion has tape too, but on the *back* bar only |
| **Sri Lanka** | White car with a **blue-white-red flag-like blur** on the front/right side, exclusive |
| **Mongolia** | Roof rack, commonly carrying camping and expedition gear. Also one of only two snorkel cars (with Kenya) |
| **Bangladesh** | Black-bar roof rack with **red side mirrors** |
| **Nigeria** | Distinctive bars plus a visible **police escort "follow car"** behind |

### Car colour

- **White** — most common worldwide, several sub-variants that are hard to split.
- **Black** — next most common: parts of Europe, South America, and **all** of Jordan.
- **"Russia car"** (black with a visible long rear antenna) — only Russia, Donetsk, Israel
  and Palestine.
- **Red** — only **Ukraine and Belgium**, sometimes with a rear antenna. This is the clean
  Ukraine-vs-Russia split, the Donetsk case aside.
- **Japan** and **Switzerland** — low-mounted, so more car and a bigger blur.

### Antennas and details

- Stubby antenna, smooth, no ridges: Mexico, Colombia, Ecuador, Brazil.
- Stubby antenna **with three ridges**: New Zealand, Hawaii, Cambodia, USA. The ridge count
  is the split from the Latin American one.
- Thin stubby antenna: Java, Indonesia specifically.
- Gen 3 white car with a visible brake light: Mexico, Colombia, Brazil, Thailand.
- Antenna **never** appears on Gen 3 in North Macedonia or Turkey.
- Side mirror with a yellow sticker: Croatia.
- Blue car with an antenna, Mediterranean setting: Italy or Croatia (2022), Slovenia (2023).
- No car visible at all: Austria, Belgium.
- Electric capture cars: Frankfurt, Hamburg, London, Ireland.
- Winter-captured Gen 3 is common in Czechia, Hungary and Bulgaria.

*The year-keyed European tables above are from a source that explicitly scopes them to
copyright dates before 2024. Check the copyright year before applying them.*

### Africa and islands

- **Senegal** — two metal roof bars, small side mirrors sometimes visible, frequent sky
  "rifts" (stitching errors).
- **Uganda** — two side mirrors, nothing else. Clean and minimal.
- **Kyrgyzstan** — white car, white roof rack, large side mirrors. (The old "Kyrgyzstan red
  car" meta is **dead**; do not use it.)
- **Guatemala** — distinctive side mirrors, visually like Kyrgyzstan's but jungle rather
  than mountains.
- **Christmas Island** — shot from the back of a silver pickup.
- **Bermuda** — black car, driving on the left.
- **Tau, Samoa** and **Providencia, Colombia** — black car, driving right (Providencia with
  an antenna).
- **St. Croix, USVI** — white car, driving left.
- **San Andrés, Colombia** — white car, driving right.
- **Sir Baniyas, UAE** — white car with a yellow outer line.

### Non-car coverage

GeoHints keeps per-category country lists for boats, snowmobiles, ATVs, cable cars,
motorcycles and trains.

- **Snowmobiles** — Andorra, Austria, Czechia, Finland, France, Italy, Slovenia, Sweden,
  Switzerland, Canada, Greenland, USA, Australia, New Zealand.
- **Follow cars** (a second vehicle visible behind) — Kenya, Nigeria, Tunisia,
  Palestine/Israel, Japan, Jordan, Malaysia, Philippines, Denmark, Ireland, UK, Canada,
  Costa Rica, USA, Australia (Cocos Islands).
- **Boats** — extensive; Japan especially, plus much of coastal SE Asia, southern Africa
  and Mediterranean/Nordic Europe.

---

## Blur meta

The nadir blur tracks generation and nothing else: magenta circle = Gen 2, car-shaped =
Gen 3, small blue-tinted or a clean logo = Gen 4, oversized and non-circular = Low Cam.

**A "double blur" is not a documented distinct phenomenon.** Sources using the phrase are
paraphrasing the Gen 2 nadir. Do not treat it as its own category.

Face and licence-plate blurring is a **global default policy**, not a country signal.

Germany's house-front blurring is real: the 2010 launch let owners opt out, and German
data-protection culture meant many did. But do not conflate that with coverage. Germany's
base Street View coverage is limited to its largest cities plus some landmarks (expanded
July 2023), so much of rural Germany has no coverage at all, independent of the blurring.
**Sparse German coverage is a privacy artifact, not a remoteness signal.**

GeoHints has a "House Numbers" page listing countries where house numbers are *legible* and
usable: Uganda (not yet visible), Israel, Russia, South Korea, Taiwan, Austria, Croatia,
Czechia, France, Greece, Latvia, Netherlands, Slovakia, Slovenia.

---

## Coverage as a clue

**Landmark or museum photospheres only, no drivable roads.** If you are on a normal paved
road at car height, none of these are candidates in official coverage: China (tourist sites
and museums), Afghanistan (a few Kabul buildings), Iraq (the National Museum), Egypt (Giza
plus a few landmarks), Pakistan, Mali, Madagascar, Martinique, Tanzania (Kilimanjaro and
Gombe), Vanuatu (Ambrym), British Indian Ocean Territory, Falkland Islands, South Georgia,
Antarctica, US Minor Outlying Islands, St. Pierre and Miquelon.

**True no-coverage regions** (absent from Wikipedia's table entirely): most of the Middle
East beyond Israel/Palestine/Jordan/Lebanon/Qatar/UAE; most of Central Africa (DRC, Chad,
CAR, Cameroon, Angola, Niger); Cuba; Haiti.

**Two live source disagreements**, flagged rather than resolved: Wikipedia lists Paraguay as
landmark-only and Venezuela as having no coverage, while geohints' 2025 generation data
shows both with Gen 3/Gen 4/Small Cam. GeoHints is the more current of the two for "does
drivable coverage exist right now", since it is maintained specifically for this. Check
before betting a round on either.

**Unofficial / "Ari" coverage.** Named after Ari Immonen, a Finnish contributor who drove
and uploaded his own 360 imagery for years; any non-Google uploader is now called an "Ari."
Tells: inconsistent quality from near-professional to dashcam-grade, unusual camera heights
and angles, sometimes a visible dashboard or steering wheel at the bottom of frame, and
coverage on isolated single roads rather than a network. Its mere presence is a clue: if
you land in dashcam-grade footage in a country that should not have Street View, you are
almost certainly in unofficial coverage. Reported examples include Albania, Armenia, rural
India and various Pacific islands.

---

## Capture date and metadata

The copyright stamp in the bottom-right is a first-class tool. Cross-reference the year
against country-specific generation-by-year tables to narrow hard. Rwanda's Gen-4-only
status and Croatia's 2022 return after an 11-year gap are both concrete examples of a year
pinning a country.

Run `geo pano <lat> <lon>` on a candidate to get the actual capture month from Google.
If your candidate's real coverage is from 2013 and you are looking at Gen 4 imagery, the
candidate is wrong.

**Not verified:** "follow-the-coverage-line" and "tracker line" did not turn up as named,
citable techniques. They appear to refer to the general practice of reading the blue
coverage overlay on the mini-map. Do not cite them as established terms.

---

## Sun and compass

The in-game compass sits lower-left. Align it against the sun's position: sun to the south
means northern hemisphere, sun to the north means southern. When the sun is not visible,
use the shadow (shadow pointing north means the sun is south, so northern hemisphere).

**This method fails near the equator** and whenever the sun is high, because inside the
tropics the sun can pass on either side depending on the date. Plonk It rates it as a
tie-breaker rather than a primary check, and notes experienced players do not usually look
at the sun at all. For the quantitative version, use `geo sun` and see `nature-and-sun.md`.
