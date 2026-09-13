# Landscape, climate, and the sun

Slower and fuzzier than infrastructure, but it carries the rounds that have no text and no
road furniture. The sun section is the rigorous part and is implemented in `geo sun`.

---

## Sun and shadows

### The one equation that matters

Given a sun altitude `h`, a sun azimuth `A` (compass bearing, clockwise from true north),
and the solar declination `δ` for the date:

```
sin(δ) = sin(φ) sin(h) + cos(φ) cos(h) cos(A)
```

This solves in closed form for latitude `φ` with **no knowledge of the time of day**, which
is what makes it usable in a game where you have a compass but no clock. `geo sun` does
exactly this and also back-solves the local solar time. It returns both algebraic branches
and returns nothing when the geometry is impossible.

Getting the inputs:
- `h = atan(object_height / shadow_length)` for a vertical object on flat ground.
- `A = (bearing the shadow points + 180) mod 360`.

Declination, NOAA Fourier series (what `geo_solver.declination` uses):

```
γ = (2π / days_in_year) × (day_of_year − 1)
δ = 0.006918 − 0.399912cos γ + 0.070257sin γ − 0.006758cos 2γ
    + 0.000907sin 2γ − 0.002697cos 3γ + 0.00148sin 3γ      [radians]
```

The rough version, good to about a degree: `δ ≈ −23.44° × cos(360/365 × (N + 10))`.

### At solar noon it collapses

```
elevation_at_noon = 90° − |latitude − declination|
```
so `latitude ≈ 90° − elevation + declination`. Fast mental math when the sun is highest.

Equinox reference (δ = 0, so latitude = 90 − elevation):

| shadow : height | sun altitude | latitude |
|---|---|---|
| 2.0 | 26° | 64° |
| 1.3 | 37° | 53° |
| 1.0 | 45° | 45° |
| 0.7 | 55° | 35° |
| 0.5 | 63° | 27° |
| 0 | 90° | 0° |

### Hemisphere from shadow direction

- Northern hemisphere at local noon: sun due south, **shadows point north**.
- Southern hemisphere at local noon: sun due north, **shadows point south**.
- Inside the tropics this flips whenever the subsolar declination exceeds your own
  latitude, so the sun passes on your poleward side. **Near the equator, azimuth is not a
  reliable hemisphere signal without the date.**

An independent second check: over a day the sun sweeps east → north → west in the northern
hemisphere and east → south → west in the southern. If you can see the sun's motion across
two frames, the handedness of that arc confirms hemisphere on its own.

### Error budget, which is the part people skip

The method is genuinely sensitive. In a round-trip test, an 8% error in the shadow ratio
plus 4 degrees of bearing error moved the answer by 5 degrees of latitude. And the
shadow-length channel degrades sharply away from noon: a documented worked case got
22°N ± 23° from the naive noon formula on an afternoon photo where the true answer was
11.5°N, and only the full hour-angle-corrected solve converged.

Practical rules:
- **Shadow direction is valid all day.** Use it for hemisphere whenever you can.
- **Shadow length is only trustworthy within about three hours of solar noon.** Outside
  that, `geo sun`'s full solve still works because it uses azimuth too, but measurement
  error dominates.
- Verify by running `geo sunpos` on your candidate and checking the predicted shadow
  against the image. Disagreement kills the candidate.
- Assumes flat ground and a vertical object. A slope or a leaning pole invalidates it.

---

## Vegetation

### Near-diagnostic single species

| Plant | Where |
|---|---|
| Grandidier's baobab | Madagascar (endemic) |
| Kauri (*Agathis australis*) | New Zealand (endemic) |
| Monkey puzzle (*Araucaria araucana*) | Chile (Araucanía), western Argentina near Neuquén |
| Paraná pine (*Araucaria angustifolia*) | Brazil, Argentina, Chile (Paraná region). A different species from monkey puzzle |
| Quindío wax palm | Colombia (national tree, very tall, distinctive silhouette) |
| Saguaro cactus | US Sonoran Desert (Arizona) |
| Joshua tree | US Mojave (CA, NV, AZ, UT) |
| Giant sequoia | US Sierra Nevada |
| Cabbage palm (*Sabal palmetto*) | US southeast coast |
| Bermuda palmetto | Bermuda |
| Makalani palm | Namibia |
| *Colophospermum mopane* | Botswana |
| Century plant / cardón | Mexico |
| Winter's bark + *Gunnera* + *Nothofagus* together | Chilean temperate rainforest, Lake District and Patagonia |
| Japanese cedar (*Cryptomeria*) | Japan (also planted in Portugal and the Azores, weaker there) |

### Weak alone, strong stacked

- **Eucalyptus** — strongest for Australia when paired with left-hand traffic and red or
  pale soil, but it is planted in Portugal, Brazil, East Africa, California, Spain and
  Chile. **Weak on its own.**
- **Palms** — the primary split is fan (palmate) vs feather (pinnate). The European fan
  palm (*Chamaerops humilis*) is one of only two palms native to continental Europe (south
  Italy, Spain, Portugal, south France, north-west Africa) and is genuinely strong for the
  Mediterranean because so few palms are cold-hardy that far north. Date palm means
  Mediterranean, Middle East or North African oases.
- **Birch / pine / spruce boreal band** — black spruce, paper birch, golden aspen,
  lodgepole pine: Canada, northern US, Scandinavia, Russia, the Baltics. Strong as a
  *climate band*, weak at country level within it.
- **Oil palm plantations** in orderly rows — Malaysia, Indonesia, West Africa, Latin
  America. Strong for tropical lowland, needs road or sign confirmation for the country.
- **Rainforest plus red laterite** — equatorial Africa (Cameroon, Uganda) or the Amazon
  basin (Brazil, Colombia, Peru).
- **Savanna with scattered acacia** — sub-Saharan Africa, especially Kenya and Tanzania.
- **Cerrado scrub with red soil** — Brazil specifically. This is what separates it from
  East Africa's red soil plus banana trees.
- **Treeless steppe** — Mongolia, Kazakhstan, central Russia.
- **Grass colour** — lush green reads wet season, brown and washed out reads dry season or
  winter. Use it as a **hemisphere cross-check**: if the sun says high summer but the grass
  is dormant, either you are in the other hemisphere or you are in a dry-season
  Mediterranean or tropical climate. Do not let it pass without resolving.

---

## Soil and geology

| Soil | Look | Where | Strength |
|---|---|---|---|
| Laterite | Rusty red, iron and aluminium rich | Australia, sub-Saharan Africa, rural Brazil, India, SE Asia | **Weak alone**, appears on four continents |
| Black cotton soil (regur) | Dark grey-black clay, cracks when dry | India's Deccan and Malwa plateaus (Maharashtra, MP, Gujarat, Karnataka, Telangana, AP, Tamil Nadu), 16-18% of India's land | Strong within India, weathered from Deccan Trap basalt |
| Volcanic | Black, porous, basaltic | Iceland, Canaries, Hawaii, Réunion | Strong for volcanic islands |
| Loess | Pale yellow-buff wind-blown silt | North China Plain, Ukrainian and Russian steppe, US Midwest, Central Europe | *Unverified this pass* |

**The stacking rule, which is how red soil actually gets used:**

- red soil + left-hand traffic + eucalyptus → **Australia**
- red soil + right-hand traffic + Portuguese or Spanish → **South America, most likely Brazil**
- red soil + Devanagari → **India**
- red soil + banana trees and lush green → **East Africa**
- red soil + cerrado scrub → **Brazil**

---

## Köppen bands as a pre-filter

Use the five groups as a coarse cut before anything country-specific.

- **A tropical** — no real winter, seasonality is wet/dry rather than warm/cold. Roughly
  between the tropics.
- **B arid** — defined by evapotranspiration deficit rather than raw rainfall. Flat
  featureless desert means Saharan Africa, the Arabian Peninsula, or Central Asia.
- **C temperate** — split by dry-season timing: `f` none, `w` winter-dry, `s` summer-dry
  (Mediterranean). Vineyards on rolling hills sit here: France, Italy, Spain, Chile,
  Argentina, South Africa's Western Cape.
- **D continental** — strong seasonal swing, winter snow, boreal forest at the poleward edge.
- **E polar** — treeless, moss and lichen.

Always run the season cross-check: snow with a high sun angle is contradictory almost
everywhere outside high elevation, and should send you back to re-examine the shadow or
the vegetation rather than being averaged away.

*Köppen is standard biogeography applied to the game, not a named community meta.*

---

## Terrain

| Landform | Formed by | Where |
|---|---|---|
| U-shaped glacial valley, fjord | Glacial erosion; a fjord is the valley flooded below sea level | Norway, Chile, New Zealand, Alaska, British Columbia |
| Karst (sinkholes, caves, pointed hills) | Limestone dissolution | Southern China, Vietnam, Philippines |
| Mesa (flat top, steep sides) | Resistant caprock over softer rock | US Southwest, South Africa, Venezuela (tepuis) |
| V-shaped fluvial valley | Water erosion, no glacial history | Rules *out* recently glaciated terrain |

---

## Sky and light

- **Saharan Air Layer** — hot dry dust lofted 1 to 4 miles up, hazing skies and reddening
  sunsets as far as the Caribbean. Called *calima* in the Canaries.
- **High-altitude sky** — clean thin dry air produces an intensely blue, low-haze sky.
  Andean Altiplano, Atacama.
- **Tropical humidity haze** — milky sky from humidity and aerosol load, year-round in the
  lowland tropics.

*This section is atmospheric science applied to the game, not a documented community meta.
It is the weakest-sourced part of this file. Do not present "Andean haze" as taught meta.*

---

## Fauna, crops, and the human landscape

- **Zebu cattle** (shoulder hump, floppy ears, dewlap) — India (~300M cattle, overwhelmingly
  zebu), Brazil, sub-Saharan Africa. Strong tropical/subtropical signal.
- **Rice paddies** (standing water, terracing) — South and Southeast Asia. In the US, rice
  grows **only** in north-central California and the Lower Mississippi Valley, which makes
  it unusually diagnostic there.
- **Sugarcane** — Brazil (dominant), Thailand, Indonesia, the Philippines.
- **Oil palm** — Malaysia, Indonesia, West Africa.
- **Vineyards on rolling hills** — Mediterranean Europe, Chile, Argentina, South Africa.
- **Coffee** — Minas Gerais dominates in Brazil.
- **Tea** — Shizuoka (36%) and Kagoshima (34%) in Japan; Rize in Turkey.

Commercial signage is usually a faster human-landscape tell than crops or fences. See
`brands.md`. *Fence and field-boundary patterns were not verified against a primary source
and are omitted rather than guessed at.*
