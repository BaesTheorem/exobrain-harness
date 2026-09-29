---
name: pokemon-go
description: Pokémon GO partner for Alex. Curates strategies against his stated goals (PvP teams, dex completion, raid prep, candy and XL farming, gym control, shinies, leveling) from his own box, current events and raid bosses, PvPoke rankings, the Pokédex, and his gyms and stops. Use when Alex mentions Pokémon GO, PoGo, his box or storage, IVs, a raid, Community Day, GO Battle League, a gym, PokéStop, Poke Genie, Pogo Lens, "what should I do in Pokémon GO", "who should I power up", "is this worth keeping", or asks for a Pokémon GO plan.
---

# Pokémon GO

Two jobs: keep Alex's Pokémon GO data flowing, and turn it into a plan against **his** goals.
Nothing here logs in to the game or touches Niantic's servers. Every lane reads public
community data or files Alex produced himself; that is the only account access that cannot
get the account banned, and it is not negotiable.

## Instruments

| Need | Tool | Notes |
|---|---|---|
| What is live right now (events, raid bosses, research, eggs, Rocket lineups, promo codes) | `pokemon-go/bin/pogo today`, `events`, `raids`, `research`, `eggs`, `rocket`, `promos`; or the `pokemon-go` MCP tools in a chat | LeekDuck's hourly scrape; local times |
| A Pokémon's stats, moves, matchups, max CP, shiny status | `pogo dex <name> [--form mega]`, `pogo type`, `pogo shiny` | pogoapi.net |
| PvP value | `pogo pvp great\|ultra\|master\|little [--find name] [--cup slug]` | PvPoke rankings; `--cups` lists the current cups |
| CP and IV math | `pogo cp`, `pogo ivs --dust` | same formulas the app uses |
| **His box** (species, CP, IVs, level, moves, candy, caught date) | `pogo box pull` then `pogo box stats\|list\|find\|dupes\|diff` | `pull` copies the Pogo Lens box off the paired iPhone over Wi-Fi (phone unlocked, same LAN) and imports it; the iCloud CSV export and Poke Genie CSVs are the fallbacks. Rows named like a CP label, or whose CP and HP fit no IVs, are frames caught mid-animation and are dropped |
| **His account** (level, XP, stardust, spend, friends, activity by month) | `pogo account show\|activity\|spend` | From the official data request; Pokémon by species name only |
| His goals and standing notes | vault `Areas/Adventure & Creativity/Pokemon GO/Pokemon GO.md` | Read it first, every time. Alex edits the Goals section himself |

Data freshness matters: say when the box was scanned (`pogo box stats` prints it) and when
events end. A box older than a few weeks is a hypothesis about his storage, not a fact.

## Curating a strategy

1. Read the vault note's **Goals** and **Constraints** (playtime, budget for coins and raid
   passes, whether he walks or drives, home and work gyms). If Goals is empty, ask for them
   in one question and stop; a plan without goals is generic advice.
2. Pull the current state: `pogo today`, `pogo box stats`, and the lanes the goals need
   (`pogo pvp` for a league goal, `pogo dex` and `pogo raids` for raid prep, `pogo events
   --days 14` for the calendar).
3. Reason from his box outward. Recommendations name specific Pokémon he owns (CP, IVs,
   level as scanned), the exact cost (stardust, candy, XL, coins), and the deadline the
   event calendar imposes. A hundo he does not own is not a plan.
4. Rank by leverage: what the calendar makes cheap this week (Community Day moves, Spotlight
   Hour candy, GO Battle League rotation, raid bosses ending) before evergreen work.
5. Say what to skip and why. Transfer lists are suggestions with a search string he can paste
   into the game; MIST never touches the game itself.
6. Write the plan into the vault note under a dated `### Plan YYYY-MM-DD` heading, above the
   previous one, and keep it short enough to read on a phone.

## Pogo Lens (the scanner app)

Repo `~/Documents/pogo-lens` (BaesTheorem/pogo-lens), iOS, XcodeGen, installed with
`ios/scripts/install.sh`. Two modes: **live scan** (a Broadcast Upload Extension receives the screen while he plays
Pokémon GO, OCRs a frame a second, confirms each read with a second frame because CP counters
and appraisal bars animate, and banners each Pokémon) and screenshot scan. Both feed the app's
box; `pogo box pull` fetches that box over Wi-Fi, and the app also exports a Poke Genie-dialect
CSV into the sync folder he picked (iCloud Drive/Pokemon GO). The
parsers are calibrated from the OCR debug files the app writes when that setting is on
(`pogolens-debug-*.json` in the same folder): read them on the Mac, adjust
`ScreenParser.swift` or `AppraisalReader.swift`, rebuild, reinstall.

Alex wants as much of the game ingested as the screen allows. Every screen is one more
classifier plus parser in `ScreenParser.swift`; add them in this order of leverage:

1. Storage list view (a screen recording scrolled through the box): name and CP for the whole
   box in one pass, so the summary-screen scans only have to cover what matters.
2. Pokédex pages: caught and seen per species, shiny, lucky, shadow, mega and XXL/XXS badges,
   which is what dex-completion goals plan against.
3. Trainer profile: level, XP to next, medals, lifetime stats (km, catches, stops, battles).
4. Today view: field, timed and special research tasks and their rewards.
5. Gym detail (defenders, team, motivation) and the Nearby raids panel, for his local gyms.
6. Items and eggs.
Then a ReplayKit broadcast extension for live scanning while he plays, instead of screenshots.

## Stops and gyms

Static locations come from Scopely's official Pokémon GO web map (`pokemongo.com/en/map`:
Gyms, Power Spots, scheduled raids, community meetups) and the Wayfarer map (every Wayspot
with its PokéStop, Gym or Power Spot usage and coordinates; needs a Wayfarer sign-in, which
requires an eligible trainer level). Both are read-only official sites; live defenders only
ever come from the game screen. Never from a
scanner backend: those run other people's accounts through a device farm and are the thing
Niantic bans.

## Privacy

Box and account exports live in gitignored `pokemon-go/data/`. Location history stays inside
the unzipped export and is never summarised out, quoted, or written to the vault.
