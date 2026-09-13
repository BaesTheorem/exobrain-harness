# geoguessr

`bin/geo` is the geolocation bench behind the `/geoguesser` skill. It exists so the parts
of placing a photo that follow a rule stop being guesswork: solar geometry, scoring math,
coverage lookup, geocoding, Overpass narrowing, and getting enough pixels on a sign to read
it. Judgment (what a bollard means, what script that is) stays with the model, and lives in
`.claude/skills/geoguesser/references/`.

## Commands

```
geo sun --height 1 --shadow 1.4 --shadow-azimuth 20 [--date 2026-07-15]
```
Latitude from a shadow, with no clock needed. Object height, shadow length in the same
units, and the compass bearing the shadow points. With `--date` you get a latitude and the
local solar time; without one it sweeps the year for a band. Returns both algebraic
branches, and returns nothing when the geometry is impossible rather than a nearest fit.

```
geo sunpos <lat> <lon> --date 2026-03-15 --solar-time 15
```
The forward check: what a shadow should look like at a known place and time. Run it against
a candidate and compare with the image.

```
geo pano <lat> <lon> [--radius 500]
```
Is there Street View here, from when, and at what car heading. Keyless.

```
geo score [--km 400] [--points 4500] [--guess lat,lon --answer lat,lon] [--map-diagonal 1500]
```
`5000 * exp(-10 * d / D)` both directions, plus great-circle distance between two points.

```
geo where <lat> <lon>
geo geocode "Wadowice" --country pl
```
Coordinates to a country and region, and a place name off a sign to coordinates.

```
geo overpass '<Overpass QL>'
```
`[out:json]` is added automatically. Put tag filters before geometry filters and keep the
area tight, or you will get a 504.

```
geo enhance shot.png --crop 400x200+1100+640 --scale 4
```
Crop, Lanczos upscale, unsharp mask. Enough to make a blurry sign legible.

## Layout

- `geo_solver.py` — the math. Closed-form, stdlib only, carries an INVARIANTS block.
- `geo_cli.py` — argument parsing and the network/image subcommands.
- `bin/geo` — launcher; puts this directory on `PYTHONPATH`.
- `bin/geo-pano` — split out because Street View lookup needs `streetlevel` under Python
  3.12 via `uv`, and the rest of the CLI should stay instant. It stubs `pyexiv2`, which
  `streetlevel` imports only for EXIF-on-download and which otherwise needs
  `brew install inih`.

Tests are in `tests/test_geo_solver.py`: the solver round-trips six known cities back to
their own latitudes, and the score curve is checked against reported values.
