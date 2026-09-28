---
name: electricity
description: Pull, persist, and analyze home electricity -- Evergy usage/cost/forecast and per-floor Nest thermostat runtime. Single source of truth for the Energy Log note in Obsidian. Use when the user asks about electricity, the power bill, energy usage, kWh, "how's my bill", "am I saving money", the thermostat(s), HVAC, AC runtime, "how much is cooling costing me", the overnight schedule experiment, or when any skill needs energy/HVAC data (daily briefing, evening winddown, monthly review).
---

# Electricity

Single source of truth for home electricity and HVAC. Other skills reference this
rather than implementing their own Evergy/Nest logic.

Two **standalone** integrations feed one Obsidian note. Both live in their own
private repos, **not** in this harness -- the only thing that crosses into the
vault is the exported **Energy Log** note. Don't move the integration code into
the harness, and don't commit pulled data or housemate names anywhere.

## The two integrations

| Integration | Repo (local) | What it owns | On-demand read (no writes) |
|-------------|--------------|--------------|----------------------------|
| **Evergy** (folded into Claude Home) | `~/Documents/claude-home/integrations/evergy` | kWh + $ usage, cost, billing-cycle forecast | `.venv/bin/python energy-pull.py --json` |
| **Nest** (folded into Claude Home) | `~/Documents/claude-home/integrations/nest` | Per-floor live state + exact cooling runtime + doorbell | `.venv/bin/python nest-poll.py --json` |

Always prefer the `--json` paths for a live read -- they print current numbers
and touch nothing. The scheduled jobs below own the writes.

### Evergy -- the authoritative $ scoreboard (delayed)
- Pulls via a fork of `opower` (`BaesTheorem/opower`, installed editable). Auth
  is screen-scraping Evergy's login, so a site redesign can break it -- patch the
  fork. **Evergy MFA must stay OFF** (opower's Evergy path has no MFA handler).
- **Latency:** Evergy is **not** real-time. Interval/daily data lags ~8-24h
  (meters batch-backhaul). So an experiment's kWh verdict lands ~next day. Treat
  Evergy as the delayed but authoritative kWh/$ scoreboard.
- Daily launchd `com.exobrain.energy-pull` at 06:30 runs `--backfill 3 --hourly 3`
  so granular TOU data accumulates. Writes the `ENERGY:AUTO` block in the note.
- `--backfill N` / `--hourly N` for history; `energy.db` (via `warehouse.py`)
  joins Evergy daily/hourly + Nest runtime + weather into one report.

### Nest -- near-real-time behavior feedback
- Multiple thermostats, **one per floor = separate AC zones/compressors**.
  Referenced generically by floor number. Which floor is **the sleeping floor**
  (usually the bill's biggest driver, since its native schedule cools overnight)
  and which zones barely run are in the gitignored config, not here.
- `nest-poll.py` samples live state every 5 min (`com.exobrain.nest-poll`) for
  the `HVAC:AUTO` block. `nest-events.py` drains Google Pub/Sub HVAC on/off
  events (`com.exobrain.nest-events`, every 10 min) for **exact** runtime that
  survives the Mac sleeping. Runtime lives in `nest-data.json`; **nest-events
  owns runtime, nest-poll is snapshot-only** (no double-counting).
- Read-only by default. Setpoint control code exists (`nest-set.py`,
  `nestlib.py`) but is dormant -- see "Control philosophy" below.

## The Energy Log note (the one vault surface)

`Areas/Money & Finances/Energy Log.md`. Four auto-managed marker blocks, each
preserves the others -- **never hand-edit between the markers**, write your own
notes above/below them:

| Block | Written by | Contents |
|-------|-----------|----------|
| `ENERGY:AUTO` | `energy-pull.py` | Cycle outlook + daily kWh/$ table |
| `HVAC:AUTO` | `nest-poll.py` | Live per-floor temp/setpoint/status + cooling-today |
| `NIGHTLOG:AUTO` | `night-log.py` | Per-night sleeping-floor runtime vs. outdoor low |
| `PRECOOL:AUTO` | `precool-log.py` | Pre-cool decision vs. result, per-band learning |

## The overnight schedule experiment

The active question: **is the sleeping-floor overnight schedule actually saving
money, or were the cheap nights just mild?** To answer it you have to hold
weather constant.

- `night-log.py` (daily `com.exobrain.nest-nightlog` at 08:00) logs, per night
  (the 22:00-07:00 window keyed by its evening date): sleeping-floor overnight
  cooling hours, whole-house hours, that night's outdoor low, and the
  morning-after kWh. Overnight minutes are event-sourced (exact, sleep-proof).
- **How to read it:** compare nights with **similar outdoor lows**. Less runtime
  at the same low = the schedule is doing real work, not just cool weather. One
  cheap night proves nothing; wait for a spread of lows (~a week).
- The sleeping floor's schedule is a **ramp** (deepest cooling at bedtime, easing
  up toward morning; the setpoints live in the native Nest schedule), so the
  compressor runs hardest in the first hours after bedtime. That early-overnight
  cooling is the lever if Alex ever wants more savings, but it is the household's
  sleep comfort, so don't argue for it; surface the tradeoff, his call.

## Rate plan & cost framing

- **Plan:** Evergy Missouri **Time-of-Use**. Peak 4-8pm ~$0.151/kWh (every day,
  no weekend exemption); off-peak midnight-6am ~$0.131; mid otherwise ~$0.141.
  The peak premium is modest (~16%) -- **total summer kWh is the bigger lever**
  than time-shifting. Rates roughly doubled June 1 (summer seasonal).
- **Demand response:** all three Nests are enrolled in the **Evergy Thermostat
  Program** -- Evergy may raise setpoints on summer weekdays 12-9pm (opt-out per
  event). Complementary to the overnight schedule (different window).
- **Cost split:** if the bill is shared, frame dollar figures as Alex's share
  per the configured split in the gitignored config, not the full bill. Still
  worth it as a whole-house win.

## Control philosophy (settled)

**Native Nest schedule = the reliable static baseline; MIST/code = dynamic
overrides only.** Alex hand-entered the 24h sleeping-floor schedule in the Nest app,
so the daily ramp no longer depends on the Mac.

Live dynamic overrides:
- **Weather-responsive afternoon pre-cool** (`nest-precool.py`, daily 14:00):
  scales the sleeping-floor pre-cool *depth* to the day's forecast high so the
  sleeping floor banks against the 4-8pm peak only as hard as the weather
  warrants -- mild days bank nothing, hot days bank deep. Tier table:
  ≤80°F→72, 81-87→70, 88-93→68, 94+→66. Guardrails: SAFE_RANGE 66-74°F,
  13:00-16:00 active window, `precool.disabled` kill switch. The native schedule
  resumes at its next setpoint change. **This is the only dynamic write today.**
  Its results loop is `precool-log.py` (the `PRECOOL:AUTO` block) -- read it to
  see whether a band's bank depth is necessary and tune the tiers from evidence.
- *Future:* a presence-based "sleeping-floor residents away → coast" override
  (pending a geofence/presence build).

Don't rebuild the dismantled Mac-side overnight enforcer (the ramp lives in the
native Nest schedule now).

## Live dashboard (read-only viewer)

`Claude Home.app` (`~/Documents/claude-home`, Flask :5016, its own private repo
`BaesTheorem/claude-home`, **not** in the harness) is a live flat/sharp window
onto the home's devices. The **Evergy puller now lives inside it** at
`integrations/evergy/` (folded in 2026-06-15); it also reads `nest-data.json`
for HVAC + the doorbell feed/snapshots. The viewer never controls thermostats.
Floor labels are genericized to numbers there too. It's the human-facing view;
this skill is still the source of truth for pulling/analyzing electricity.

## Privacy

- Integration code stays in its own repos; **only the Energy Log note** crosses
  into the vault. Never copy pulled data (`energy-data.json`, `nest-data.json`)
  or credentials into the harness.
- **Never commit housemate real names** or the cost-split details to any repo.
  Refer to floors and "housemates" generically.

## When other skills need this

- **Daily briefing / evening winddown:** read the Energy Log note (or the
  `--json` paths) for current cycle cost-vs-typical and any overnight anomaly.
- **Monthly review:** pull the cycle forecast and the night-log trend.
- Don't approximate kWh or cost -- read actual pulled data, same discipline as
  the health skill.
