# backpacking

A toolkit that turns a `trip.json` into a shareable backpacking plan: routed day segments on real trail data, USGS elevation profiles, USFS land ownership, USGS creeks, GPX files, an AllTrails custom route, and an interactive web page published as an unlisted page on the personal site.

The `/backpacking` skill (`.claude/skills/backpacking/SKILL.md`) has the research and design rules. This file covers the commands and the config format.

## Commands

```
backpacking/bin/trip build     TRIP_DIR   route + elev + layers + check + web
backpacking/bin/trip shots     TRIP_DIR   desktop and phone screenshots, JS error check, og.jpg
backpacking/bin/trip alltrails TRIP_DIR   upload each plan's GPX to AllTrails, save the links
backpacking/bin/trip publish   TRIP_DIR   copy to the site repo as trips/<slug>-<token>/ and push
```

You can also run each step alone: `route`, `elev`, `layers`, `check`, `web`. Run `web` again after `alltrails`, so the page gets the AllTrails link.

`check` stops with an error if a waypoint marked `"camp": true` is not on USFS land.

## Data sources

| Step | Source |
| --- | --- |
| Route geometry | OpenStreetMap trail relations (`osm.relations`), plus every highway in `osm.extra_bbox` at 3x cost for spur roads |
| Elevation | USGS 3DEP point query service (EPQS), sampled every 0.06 mi, gain with a 10 ft hysteresis |
| Land ownership | USFS EDW BasicOwnership |
| Creeks | USGS NHD large-scale flowlines. Named perennial streams only, because intermittent ones are often dry |
| Map imagery | USGS National Map imagery tiles |

The OSM, USFS, NHD and EPQS responses are cached in `backpacking/cache/`, which git ignores. Delete a cache file to fetch it again.

## trip.json

- `slug`, `title`, `subtitle`, `page_title`, `page_description`, `difficulty`
- `bbox`: `[south, west, north, east]`, the data area and the map's pan limit
- `osm.relations`: OSM relation ids for the trail system. `osm.extra_bbox`: boxes whose roads and paths are also routable
- `water.main`: the NHD name of the creek drawn in blue. Optional: `label_box`, `label_at`, `exclude`
- `waypoints`: id to `{name, lat, lon, label, side ("l" or "r"), text, source}`. Flags: `tap`, `camp`, `approx`, `route_only` (a routing point that is not shown)
- `milestones`: the global numbering order of the shown waypoints
- `plans`: one entry per tab, `{id, tab, gpx_name, eyebrow, title, rec, milestones, side_trips, notes, days}`
  - each day is `{name: "Day 1: ...", via: [waypoint ids]}`. Flags: `side` (out and back from camp), `optional` (drawn dotted and left out of the totals), and `track_gpx` (use a GPX track instead of routing)
- `why`: `{icon, title, text, plans?, tag?}`, the route rationale. Without `plans` an entry shows on every tab
- `conditions`: `[icon, title, text]`. `emergency`: `[label, shown, tel]`. `sources_html`. Optional `pdf`

Icons are Material Symbols Outlined names. The page loads only the icons it uses.

## Outputs

`TRIP_DIR/build/` holds `routes.json`, `layers.json`, `site/` (the page, the GPX files, the font) and `shots/`. `links.json` and `publish.json` hold the AllTrails links and the unlisted path. Git ignores all of them, because the path is the only thing that keeps the page unlisted.

## Requirements

`uv` and Google Chrome. The site repo must be cloned at `~/Documents/becomingstronger.github.io`. The AllTrails upload needs a saved session: run `alltrails/bin/alltrails auth --from-chrome`.
