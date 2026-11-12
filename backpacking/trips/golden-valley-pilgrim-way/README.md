# Golden Valley Pilgrim Way: 8-night plan

A map page and GPX for the Golden Valley Pilgrim Way (Herefordshire), with one night in each church night sanctuary. The plan is the Abbeydore Deanery's official 7-day line, plus an extra night at Craswall and short detours to Snodhill Castle, Moccas church and Craswall Priory.

The `trip` pipeline in `backpacking/bin` uses US data sources (USGS, USFS, NHD), so this trip has its own small build.

## Rebuild

1. Get the route line. Download the Deanery's OS Maps route page (`explore.osmaps.com/route/30852736`). Then save the `TRACK_SEGMENT` line and the `WAYPOINT` features from `__NEXT_DATA__` to `src/route7.json` as `{"line": [[lon,lat],...], "wps": [[lon,lat,km,elev],...]}`.
2. Measure the sites against the line: `python3 tools/sites.py src/route7.json src/sites.json build/sites_measured.json`
3. Route the detours: `python3 tools/route_side.py src/side_legs.json src/side.json`
4. Build the page: `python3 tools/build.py`. The output is in `build/site/` (`index.html` and `gvpw-8-night.gpx`).

`src/plan.json` holds the days, the stop notes and the holy well positions. The well positions are approximate.
