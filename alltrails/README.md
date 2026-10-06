# alltrails

A command-line tool for AllTrails. It finds trails and shows their stats, recent dated reviews, the route as GPX, and the 7-day trailhead forecast.

## Warning: the data is crowd-sourced

AllTrails users contribute the lengths, elevation, difficulty, routes, and reviews. Use this data only as a starting point. Before a plan depends on a value, make sure that the land manager (USFS, NPS, or the state agency) gives the same value. Because of this, the output labels all stats as "AllTrails (crowd-sourced)".

## Data sources

The tool uses two sources:

- `search`, `trail`, and `weather` use the official AllTrails MCP endpoint at `https://www.alltrails.com/mcp`. A key is not necessary.
- `reviews` and `gpx` read the public trail web pages. Plain HTTP requests to these pages get a 403 from the bot protection. Thus the tool loads each page in system Chrome with the window off screen. It reads the data that the page embeds, not the text on the screen.

The MCP endpoint is also registered for Claude Code at user scope:

```
claude mcp add --scope user --transport http alltrails https://www.alltrails.com/mcp
```

Its tools are `search_trails_by_name`, `find_trails_near_location`, `find_trails_within_bounds`, `get_trail_details`, and `get_trail_weather_overview`. It has no reviews tool and no route geometry. This CLI supplies those two items.

## Usage

```
alltrails/bin/alltrails search "Cedar Creek Trail" --near 38.85,-92.15 --limit 5
alltrails/bin/alltrails trail us/missouri/moon-loop --reviews 5
alltrails/bin/alltrails reviews smith-creek-loop-trail --since 2026-05-01
alltrails/bin/alltrails gpx cedar-creek-trail-system -o cedar-creek.gpx
alltrails/bin/alltrails weather 10033751
```

A trail reference can be a trail id, a full slug (`us/missouri/moon-loop`), a short slug (`moon-loop`), or an AllTrails URL. Add `--json` to `search`, `trail`, `reviews`, or `weather` to get structured output. Put `--fresh` before the command name to ignore the cache.

## Limits

- `reviews` shows only the first page that the trail page embeds, which is approximately 5 reviews, newest first. To read older reviews, use the website.
- `weather` gives only the daily high and low temperature and the alert text. Precipitation is not in the MCP data.
- GPX tracks have latitude and longitude only, with no elevation.
- The tool waits 4 seconds between two page loads. It keeps MCP results for 6 hours and page data for 12 hours in `cache/`, which git ignores.
- The bot protection can block a page load. If this occurs, wait some minutes and try again.

## Requirements

`uv` and Google Chrome. The first time you use the tool, uv installs Playwright into the uv cache.
