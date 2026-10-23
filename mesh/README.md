# mesh

Terrain map and line-of-sight table for a small LoRa mesh (Meshtastic or MeshCore, 915 MHz).

`build_map.py` reads a site list and a USGS 3DEP bare-earth grid. It calculates the terrain clearance and the 60% Fresnel margin for each pair of sites, at a 4/3 earth radius. It writes these files to the `out_dir` of the site list:

| File | Content |
|---|---|
| `map.html` | MapLibre map with elevation tint, hillshade, 10 ft contours, and a color for the result of each link. Click a link to see its elevation profile. A button shows 3D terrain. |
| `map.png` | A static image of the map, for a note |
| `profiles.png` | The elevation profile from the first site to each other site |
| `links.json` | The full link table |

## Use

```
uv run mesh/build_map.py [sites.json] [--no-png]
```

The first run downloads the elevation grid to `mesh/cache/` (approximately 12 MB). To change the area, change `dem_bbox` and remove `cache/dem.tif`.

## Missing files

`sites.json` and `cache/` are gitignored, because the site list contains private addresses. To make a new site list, write this structure:

```json
{
  "out_dir": "/path/outside/the/repo",
  "title": "My mesh",
  "dem_bbox": [-94.645, 39.02, -94.535, 39.088],
  "default_profile": ["home", "friend"],
  "same_building": [["a", "b"]],
  "sites": [
    {"id": "home", "name": "Home", "people": "", "address": "", "lat": 0, "lon": 0,
     "floor": 3, "facing": "S", "note": ""}
  ]
}
```

- The first site is the root: `profiles.png` and the path search start from it.
- `floor` sets the antenna height: 10 ft per floor, with the node at mid-window.
- `facing` is a compass point (`N`, `SE`), `all`, or `?`. The table records each link that goes through the building instead of through a window.
- Pairs in `same_building` get no link.

## Limits

- The grid is bare earth. Trees and buildings are not in the model, so a clear link can still fail.
- The tool does not calculate a link budget. The field test with hop limit 0 decides.
