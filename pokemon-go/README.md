# Pokemon Go: MCP server + `pogo` CLI

Two ways to get Pokemon Go data into MIST, both read-only and both fed by public
community sources. Neither touches a player account: Niantic publishes no player
API, the reverse-engineered clients from 2016 (pgoapi and its ports) have been dead
for years, and anything that logs into the game from a script is a ban risk.

| Piece | What | Where |
|---|---|---|
| **MCP server** `pokemon-go` | 43 tools over live events, raids, field research, egg pools, Team GO Rocket lineups and promo codes, with a type-weakness calculator | Fork of [GhostTypes/pokemon-go-mcp](https://github.com/GhostTypes/pokemon-go-mcp) (MIT) at `~/Documents/pokemon-go-mcp`, pushed to [BaesTheorem/pokemon-go-mcp](https://github.com/BaesTheorem/pokemon-go-mcp); launcher `bin/pokemon-go-mcp` |
| **CLI** `pogo` | The same live data for scripts, briefings and watchers, plus the Pokedex (stats, moves, evolutions, shiny status, matchups), PvPoke rankings, and CP / IV math | `bin/pogo` (shim) and `pogocli.py`, stdlib only |

## Setup

```sh
# MCP server: clone the fork and build its venv (Python 3.10+, uv)
git clone https://github.com/BaesTheorem/pokemon-go-mcp.git ~/Documents/pokemon-go-mcp
cd ~/Documents/pokemon-go-mcp && uv sync

# register it (already in the harness .mcp.json, which is gitignored)
#   "pokemon-go": {"command": "<harness>/pokemon-go/bin/pokemon-go-mcp", "args": []}

# CLI: nothing to install
pokemon-go/bin/pogo -h
```

## `pogo` lanes

```
pogo today                          active events, today's hours, current raid bosses, promo codes
pogo events [--type T] [--days N]   active and upcoming; --all includes ended
pogo event zorua                    one event in detail: spawns, bonuses, shinies, research
pogo raids [--tier 5|mega|shadow] [--type dragon] [--shiny]
pogo research [query] [--shiny]     field research tasks and their rewards
pogo eggs [--km 10] [--shiny] [--regional] [--sync]
pogo rocket [giovanni|sierra|fire|<pokemon>] [--shiny]   lineups with per-Pokemon weaknesses
pogo promos
pogo dex charizard [--form Mega] [--all-forms]
pogo type fire flying               attacking and defending multipliers
pogo shiny mewtwo                   where the shiny has been found
pogo pvp great|ultra|master|little [--cup retro] [--top 25] [--find azumarill] [--cups]
pogo cp mewtwo --level 40 [--iv 15/14/13]
pogo ivs charizard --cp 1587 --hp 128 --dust 2500     IV combinations that fit
pogo refresh                        drop the on-disk cache
```

Every listing lane takes `--json`. `--no-cache` forces a refetch for one run.
Event times are LeekDuck's local-time strings and are printed as this machine's
local time. IV results assume a normal (not weather-boosted, not lucky-trade)
encounter; hatches and raid catches are level 20, so pass `--level 20` for those.

## Data sources

| Source | Used for | Refresh | Terms |
|---|---|---|---|
| [LeekDuck.com](https://leekduck.com), scraped hourly by the [GhostTypes/pokemon-go-mcp data branch](https://github.com/GhostTypes/pokemon-go-mcp/tree/data) | events, raids, research, eggs, rocket lineups, promo codes | 1 h cache | Credit LeekDuck. [ScrapedDuck](https://github.com/bigfoott/ScrapedDuck) (LeekDuck's permissioned scraper, same schema) is the fallback: set `POGO_DATA_URL=https://raw.githubusercontent.com/bigfoott/ScrapedDuck/data`; its rocket file is named `rocketLineups.json` and has a different shape, so the `rocket` lane needs the default source |
| [pogoapi.net](https://pogoapi.net) | Pokedex stats, types, moves, evolutions, buddy distance, rarity, shiny status, type chart, CP multipliers, power-up costs | 24 h cache | Free public JSON; the CP multiplier table stops at level 45 and the CLI extends it with the game's 0.0025 per half-level step (verified: level 51 hundo CP matches pogoapi's `max_cp` for all 1,420 stat rows) |
| [PvPoke](https://github.com/pvpoke/pvpoke) (MIT) | league and cup rankings, movesets, matchups | 24 h cache | Rankings are PvPoke's simulation output, not Niantic data |

The MCP server's bundled `data/` files are a snapshot; the fork patches its client
to read the live data branch with a disk cache (`~/.cache/pogo-mcp`, 1 h TTL,
`POGO_MCP_DATA_URL` / `POGO_MCP_CACHE_TTL` / `POGO_MCP_CACHE_DIR` to override,
`POGO_MCP_DATA_URL=local` for offline). Upstream's test suite passes with and
without the network.

Cache for the CLI: `~/Library/Caches/pogo-cli` (`POGO_CACHE_DIR`). On a network
failure a stale cached copy is used with a warning on stderr.

## Tests

`pytest tests/test_pogo_cli.py` covers the CP and HP formulas against known in-game
values, the IV solver round trip, type matchup math, event status classification
and the text helpers. Nothing in the tests touches the network.
