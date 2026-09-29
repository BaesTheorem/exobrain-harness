#!/usr/bin/env python3
"""pogo: Pokemon Go from the terminal, stdlib only.

Lanes
  today                     active events, today's hours, current raid bosses, promo codes
  events [--type T] [--days N] [--all]
  event <query>             one event in detail (spawns, bonuses, shinies, research)
  raids [--tier T] [--type T] [--shiny]
  research [query] [--shiny]
  eggs [--km N] [--shiny] [--regional] [--sync]
  rocket [query] [--shiny]  Team GO Rocket lineups with weaknesses
  promos                    active promo codes
  dex <name|#> [--form F]   stats, max CP, moves, evolutions, buddy km, shiny status, matchups
  type <T> [T2]             attacking and defending multipliers
  shiny <name>              where a shiny has been found
  pvp <league> [--cup C] [--top N] [--find NAME] [--cups]
  cp <name> --level L [--iv A/D/S] [--form F]
  ivs <name> --cp N --hp N (--dust D | --level L) [--form F]
  refresh                   drop the on-disk cache
  box import|list|find|stats|dupes|diff      your storage, from a Poke Genie or Calcy IV CSV
  account import|show|activity|spend         the official data-request export
  inbox [--notify] [--dry-run]               import new exports from iCloud Drive/Pokemon GO and ~/Downloads
Every listing lane takes --json for scripts.

Data (credits and terms in README.md)
  LeekDuck.com, via the hourly scrape on the GhostTypes/pokemon-go-mcp data branch:
    events, raids, research, eggs, rocket lineups, promo codes (POGO_DATA_URL overrides)
  pogoapi.net: Pokedex stats, types, moves, evolutions, shiny status, type chart,
    CP multipliers, power-up costs
  PvPoke (github.com/pvpoke/pvpoke): league and cup rankings

Cache: ~/Library/Caches/pogo-cli (POGO_CACHE_DIR); live data 1 h, reference data 24 h.
Event times are LeekDuck's local-time strings and are treated as this machine's local time.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

LIVE_URL = os.environ.get(
    "POGO_DATA_URL", "https://raw.githubusercontent.com/GhostTypes/pokemon-go-mcp/data"
).rstrip("/")
POGOAPI_URL = "https://pogoapi.net/api/v1"
PVPOKE_URL = "https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data"
CACHE_DIR = Path(os.environ.get("POGO_CACHE_DIR") or Path.home() / "Library" / "Caches" / "pogo-cli")
LIVE_TTL = 3600
REF_TTL = 86400
UA = "pogo-cli/1.0 (personal terminal client)"
LEAGUES = {"great": 1500, "ultra": 2500, "master": 10000, "little": 500}
TYPES = [
    "Bug", "Dark", "Dragon", "Electric", "Fairy", "Fighting", "Fire", "Flying", "Ghost",
    "Grass", "Ground", "Ice", "Normal", "Poison", "Psychic", "Rock", "Steel", "Water",
]
NO_CACHE = False


# ---------- plumbing ----------

def warn(msg: str) -> None:
    print(f"pogo: {msg}", file=sys.stderr)


def norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def strip_html(s: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def title_move(move_id: str) -> str:
    return move_id.replace("_FAST", "").replace("_", " ").title()


def clean(s: Any) -> str:
    """Strip tags and collapse whitespace, including the non-breaking spaces LeekDuck uses."""
    return " ".join(strip_html(s).split())


def pretty_id(species_id: str) -> str:
    return species_id.replace("_", " ").title()


def cp_range(cp: Any) -> str:
    """LeekDuck gives CP as {min, max} in most files and as a bare number in some."""
    if isinstance(cp, dict):
        return f"{cp.get('min', '?')}-{cp.get('max', '?')}"
    return str(cp) if cp not in (None, "") else "?"


def fetch(url: str, ttl: int) -> Any:
    """GET a JSON document through the on-disk cache; stale copy on network failure."""
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
    age = time.time() - path.stat().st_mtime if path.exists() else None
    if age is not None and age < ttl and not NO_CACHE:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
        if age is not None:
            warn(f"{url}: {e}; using the cached copy from {age / 3600:.1f} h ago")
            return json.loads(path.read_text(encoding="utf-8"))
        raise SystemExit(f"pogo: cannot fetch {url}: {e}") from e
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return data


def live(name: str) -> list[dict[str, Any]]:
    data = fetch(f"{LIVE_URL}/{name}.json", LIVE_TTL)
    if not isinstance(data, list):
        raise SystemExit(f"pogo: unexpected shape for {name}.json")
    return data


def ref(name: str) -> Any:
    return fetch(f"{POGOAPI_URL}/{name}.json", REF_TTL)


def parse_local(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s[:19])


def fmt_range(start: dt.datetime, end: dt.datetime) -> str:
    if start.date() == end.date():
        return f"{start:%a %b %-d %H:%M} to {end:%H:%M}"
    return f"{start:%b %-d %H:%M} to {end:%b %-d %H:%M}"


def table(rows: list[list[Any]], headers: list[str] | None = None) -> None:
    cells = [[str(c) for c in r] for r in rows]
    if headers:
        cells = [headers] + cells
    if not cells:
        return
    widths = [max(len(r[i]) for r in cells) for i in range(len(cells[0]))]
    for n, r in enumerate(cells):
        print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip())
        if headers and n == 0:
            print("  ".join("-" * w for w in widths))


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ---------- game math (pure, testable) ----------

def cpm_table(raw: list[dict[str, Any]], top: float = 55.0) -> dict[float, float]:
    """Level -> CP multiplier.

    pogoapi publishes levels 1 to 45. From level 40 up the game adds exactly 0.0025 per
    half level, so the table is extended from its last published value (anchoring there,
    not at 40, keeps the game's ...9999 constants and the CP floor exact).
    """
    cpm = {float(x["level"]): float(x["multiplier"]) for x in raw}
    last = max(cpm)
    level = last + 0.5
    while level <= top:
        cpm[level] = round(cpm[last] + 0.0025 * (level - last) * 2, 8)
        level += 0.5
    return cpm


def calc_cp(atk: int, dfn: int, sta: int, ivs: tuple[int, int, int], cpm: float) -> int:
    a, d, s = ivs
    return max(10, math.floor((atk + a) * math.sqrt(dfn + d) * math.sqrt(sta + s) * cpm * cpm / 10))


def calc_hp(sta: int, iv: int, cpm: float) -> int:
    return max(10, math.floor((sta + iv) * cpm))


def solve_ivs(
    base: tuple[int, int, int], cp: int, hp: int, levels: list[float], cpm: dict[float, float]
) -> list[tuple[float, int, int, int]]:
    """Every (level, atk, def, sta) IV combination that yields exactly this CP and HP."""
    atk, dfn, sta = base
    out = []
    for level in levels:
        m = cpm[level]
        sta_ivs = [s for s in range(16) if calc_hp(sta, s, m) == hp]
        if not sta_ivs:
            continue
        for s in sta_ivs:
            for a in range(16):
                for d in range(16):
                    if calc_cp(atk, dfn, sta, (a, d, s), m) == cp:
                        out.append((level, a, d, s))
    return out


def defensive_matchups(chart: dict[str, dict[str, float]], types: list[str]) -> dict[str, float]:
    """Attacking type -> multiplier when hitting a Pokemon with these types."""
    out = {}
    for attacker in chart:
        mult = 1.0
        for t in types:
            mult *= chart[attacker][t]
        out[attacker] = round(mult, 3)
    return out


def matchup_lines(mults: dict[str, float]) -> tuple[str, str]:
    weak = sorted(((t, m) for t, m in mults.items() if m > 1), key=lambda x: (-x[1], x[0]))
    resist = sorted(((t, m) for t, m in mults.items() if m < 1), key=lambda x: (x[1], x[0]))
    fmt = lambda xs: ", ".join(f"{t} x{m:g}" for t, m in xs) or "none"
    return fmt(weak), fmt(resist)


# ---------- Pokedex ----------

def all_stat_rows() -> list[dict[str, Any]]:
    """pogoapi's pokemon_stats plus the mega evolutions, shaped as extra forms."""
    rows = list(ref("pokemon_stats"))
    for m in ref("mega_pokemon"):
        st = m.get("stats") or {}
        rows.append({
            "pokemon_id": m["pokemon_id"], "pokemon_name": m["pokemon_name"],
            "form": " ".join(m.get("mega_name", "Mega").replace(m["pokemon_name"], "").split()) or "Mega",
            "base_attack": st.get("base_attack"), "base_defense": st.get("base_defense"),
            "base_stamina": st.get("base_stamina"), "_mega": m,
        })
    return rows


def dex_entries(query: str) -> list[dict[str, Any]]:
    """All form rows (including megas) matching a dex number or a name."""
    stats = all_stat_rows()
    if query.lstrip("#").isdigit():
        n = int(query.lstrip("#"))
        return [s for s in stats if s["pokemon_id"] == n]
    q = norm(query)
    exact = [s for s in stats if norm(s["pokemon_name"]) == q]
    if exact:
        return exact
    loose = [s for s in stats if q in norm(s["pokemon_name"])]
    ids = sorted({s["pokemon_id"] for s in loose})
    if len(ids) == 1:
        return loose
    if ids:
        names = sorted({f"#{s['pokemon_id']} {s['pokemon_name']}" for s in loose})
        raise SystemExit("pogo: ambiguous, pick one of: " + ", ".join(names))
    raise SystemExit(f"pogo: no Pokemon matches {query!r}")


def form_names(e: dict[str, Any]) -> list[str]:
    """Labels a --form value may match: the form, and for megas the full mega name too."""
    names = [e["form"]]
    if e.get("_mega"):
        names.append(e["_mega"].get("mega_name", ""))
    return names


def pick_form(entries: list[dict[str, Any]], form: str | None) -> list[dict[str, Any]]:
    if form:
        q = norm(form)
        hits = [e for e in entries if any(q == norm(n) for n in form_names(e))]
        hits = hits or [e for e in entries if any(q in norm(n) for n in form_names(e))]
        if not hits:
            raise SystemExit("pogo: forms available: " + ", ".join(e["form"] for e in entries))
        return hits
    normal = [e for e in entries if e["form"] == "Normal"]
    return normal or entries[:1]


def by_id_form(rows: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    return {(r["pokemon_id"], r["form"]): r for r in rows}


def cmd_dex(a: argparse.Namespace) -> None:
    entries = dex_entries(a.name)
    forms = entries if a.all_forms else pick_form(entries, a.form)
    types = by_id_form(ref("pokemon_types"))
    moves = by_id_form(ref("current_pokemon_moves"))
    evos = by_id_form(ref("pokemon_evolutions"))
    chart = ref("type_effectiveness")
    cpm = cpm_table(ref("cp_multiplier"))
    shiny = ref("shiny_pokemon")
    released = ref("released_pokemon")
    rarity = {(r["pokemon_id"], r["form"]): tier for tier, rows in ref("pokemon_rarity").items() for r in rows}
    buddy = {(r["pokemon_id"], r["form"]): km for km, rows in ref("pokemon_buddy_distances").items() for r in rows}
    pre = {}
    for src in ref("pokemon_evolutions"):
        for ev in src.get("evolutions", []):
            pre.setdefault((ev["pokemon_id"], ev["form"]), []).append((src["pokemon_name"], src["form"]))

    out = []
    for e in forms:
        mega = e.get("_mega")
        key = (e["pokemon_id"], "Normal" if mega else e["form"])
        base = (e["base_attack"], e["base_defense"], e["base_stamina"])
        tlist = mega["type"] if mega else types.get(key, {}).get("type", [])
        mults = defensive_matchups(chart, tlist) if tlist else {}
        weak, resist = matchup_lines(mults) if mults else ("?", "?")
        mv = moves.get(key, {})
        sh = shiny.get(str(e["pokemon_id"]), {})
        shiny_from = [k.replace("found_", "") for k, v in sh.items() if k.startswith("found_") and v]
        rec = {
            "id": e["pokemon_id"], "name": e["pokemon_name"], "form": e["form"], "types": tlist,
            "base_stats": {"attack": base[0], "defense": base[1], "stamina": base[2]},
            "max_cp": {f"L{lv:g}": calc_cp(*base, (15, 15, 15), cpm[lv]) for lv in (40.0, 50.0, 51.0)},
            "fast_moves": mv.get("fast_moves", []), "elite_fast_moves": mv.get("elite_fast_moves", []),
            "charged_moves": mv.get("charged_moves", []), "elite_charged_moves": mv.get("elite_charged_moves", []),
            "evolves_into": [f"{x['pokemon_name']} ({x['candy_required']} candy{'' if x['form'] == 'Normal' else ', ' + x['form']})" for x in evos.get(key, {}).get("evolutions", [])],
            "evolves_from": [n if f == "Normal" else f"{n} ({f})" for n, f in pre.get(key, [])],
            "buddy_km": buddy.get(key), "rarity": rarity.get(key, "Standard"),
            "mega_energy": {"first": mega["first_time_mega_energy_required"], "after": mega["mega_energy_required"]} if mega else None,
            "released": str(e["pokemon_id"]) in released,
            "shiny_found": shiny_from, "weak_to": weak, "resists": resist,
        }
        out.append(rec)
    if a.json:
        emit_json(out)
        return
    for r in out:
        form = "" if r["form"] == "Normal" else f"  [{r['form']}]"
        print(f"#{r['id']} {r['name']} ({'/'.join(r['types']) or '?'}){form}")
        b = r["base_stats"]
        print(f"  Base stats   ATK {b['attack']}  DEF {b['defense']}  STA {b['stamina']}")
        print("  Max CP       " + "  ".join(f"{k} {v}" for k, v in r["max_cp"].items()) + "  (15/15/15)")
        elite = lambda xs: f"  | elite: {', '.join(xs)}" if xs else ""
        print(f"  Fast         {', '.join(r['fast_moves']) or '?'}{elite(r['elite_fast_moves'])}")
        print(f"  Charged      {', '.join(r['charged_moves']) or '?'}{elite(r['elite_charged_moves'])}")
        if r["evolves_from"]:
            print(f"  Evolves from {', '.join(r['evolves_from'])}")
        if r["evolves_into"]:
            print(f"  Evolves into {', '.join(r['evolves_into'])}")
        km = f"{r['buddy_km']} km" if r["buddy_km"] else "?"
        print(f"  Buddy {km}   Rarity {r['rarity']}   Released {'yes' if r['released'] else 'no'}   Shiny from: {', '.join(r['shiny_found']) or 'not released'}")
        if r["mega_energy"]:
            print(f"  Mega energy  {r['mega_energy']['first']} first time, then {r['mega_energy']['after']}")
        print(f"  Weak to      {r['weak_to']}")
        print(f"  Resists      {r['resists']}")
        print()


def cmd_type(a: argparse.Namespace) -> None:
    chart = ref("type_effectiveness")
    types = []
    for t in [a.type] + ([a.type2] if a.type2 else []):
        hit = [x for x in TYPES if norm(x) == norm(t)]
        if not hit:
            raise SystemExit("pogo: types are " + ", ".join(TYPES))
        types.append(hit[0])
    if a.json:
        emit_json({"types": types, "attacking": {t: chart[t] for t in types}, "defending": defensive_matchups(chart, types)})
        return
    for t in types:
        strong = ", ".join(f"{d} x{m:g}" for d, m in chart[t].items() if m > 1) or "none"
        weakhit = ", ".join(f"{d} x{m:g}" for d, m in chart[t].items() if m < 1) or "none"
        print(f"{t} attacks")
        print(f"  Super effective vs   {strong}")
        print(f"  Not very effective vs {weakhit}")
    weak, resist = matchup_lines(defensive_matchups(chart, types))
    print(f"{'/'.join(types)} defends")
    print(f"  Weak to   {weak}")
    print(f"  Resists   {resist}")


def cmd_shiny(a: argparse.Namespace) -> None:
    e = pick_form(dex_entries(a.name), None)[0]
    sh = ref("shiny_pokemon").get(str(e["pokemon_id"]))
    if a.json:
        emit_json(sh or {"id": e["pokemon_id"], "name": e["pokemon_name"], "shiny": False})
        return
    if not sh:
        print(f"{e['pokemon_name']}: shiny not released")
        return
    found = [k.replace("found_", "") for k, v in sh.items() if k.startswith("found_") and v]
    print(f"{e['pokemon_name']}: shiny found via {', '.join(found) or 'nothing recorded'}")


# ---------- CP and IV math ----------

def base_for(name: str, form: str | None) -> tuple[dict[str, Any], tuple[int, int, int]]:
    e = pick_form(dex_entries(name), form)[0]
    return e, (e["base_attack"], e["base_defense"], e["base_stamina"])


def parse_ivs(s: str) -> tuple[int, int, int]:
    parts = [int(x) for x in re.split(r"[/,\s]+", s.strip()) if x]
    if len(parts) != 3 or not all(0 <= p <= 15 for p in parts):
        raise SystemExit("pogo: --iv wants attack/defense/stamina, each 0 to 15, like 15/14/13")
    return parts[0], parts[1], parts[2]


def cmd_cp(a: argparse.Namespace) -> None:
    e, base = base_for(a.name, a.form)
    cpm = cpm_table(ref("cp_multiplier"))
    level = float(a.level)
    if level not in cpm:
        raise SystemExit("pogo: level must be 1 to 55 in half steps")
    ivs = parse_ivs(a.iv)
    cp, hp = calc_cp(*base, ivs, cpm[level]), calc_hp(base[2], ivs[2], cpm[level])
    if a.json:
        emit_json({"name": e["pokemon_name"], "form": e["form"], "level": level, "ivs": ivs, "cp": cp, "hp": hp})
        return
    print(f"{e['pokemon_name']} L{level:g} {ivs[0]}/{ivs[1]}/{ivs[2]}: CP {cp}, HP {hp}")


def cmd_ivs(a: argparse.Namespace) -> None:
    e, base = base_for(a.name, a.form)
    cpm = cpm_table(ref("cp_multiplier"))
    if a.level:
        levels = [float(a.level)]
    elif a.dust:
        req = ref("pokemon_powerup_requirements")
        levels = sorted(float(r["current_level"]) for r in req.values() if r["stardust_to_upgrade"] == a.dust)
        if not levels:
            costs = sorted({r["stardust_to_upgrade"] for r in req.values()})
            raise SystemExit("pogo: no level costs that much stardust; costs are " + ", ".join(map(str, costs)))
    else:
        raise SystemExit("pogo: give --dust (the power-up cost shown in game) or --level")
    hits = solve_ivs(base, a.cp, a.hp, levels, cpm)
    recs = [{"level": lv, "attack": x, "defense": y, "stamina": z, "percent": round((x + y + z) / 45 * 100, 1)} for lv, x, y, z in hits]
    if a.json:
        emit_json({"name": e["pokemon_name"], "form": e["form"], "cp": a.cp, "hp": a.hp, "levels": levels, "matches": recs})
        return
    if not recs:
        print(f"{e['pokemon_name']}: no IV combination gives CP {a.cp} and HP {a.hp} at level(s) {', '.join(f'{l:g}' for l in levels)}. Check the form, the dust cost, or whether it is weather boosted or a lucky/purified special case.")
        return
    pcts = [r["percent"] for r in recs]
    print(f"{e['pokemon_name']} CP {a.cp} HP {a.hp}: {len(recs)} combination(s), {min(pcts):g}% to {max(pcts):g}%")
    table([[f"L{r['level']:g}", r["attack"], r["defense"], r["stamina"], f"{r['percent']:g}%"] for r in recs[:40]], ["level", "atk", "def", "sta", "iv"])
    if len(recs) > 40:
        print(f"  ... {len(recs) - 40} more; use --json for all")


# ---------- live LeekDuck data ----------

def event_rows(events: list[dict[str, Any]], now: dt.datetime) -> list[dict[str, Any]]:
    rows = []
    for e in events:
        try:
            s, en = parse_local(e["start"]), parse_local(e["end"])
        except (KeyError, ValueError, TypeError):
            continue
        status = "NOW" if s <= now <= en else ("ended" if en < now else "upcoming")
        rows.append({**e, "_start": s, "_end": en, "_status": status})
    return sorted(rows, key=lambda r: (r["_start"], r["_end"]))


def cmd_events(a: argparse.Namespace) -> None:
    now = dt.datetime.now()
    rows = event_rows(live("events"), now)
    if a.type:
        rows = [r for r in rows if norm(a.type) in norm(r["eventType"])]
    if not a.all:
        rows = [r for r in rows if r["_status"] != "ended"]
        if a.days:
            rows = [r for r in rows if r["_start"] <= now + dt.timedelta(days=a.days)]
    if a.json:
        emit_json([{k: v for k, v in r.items() if not k.startswith("_")} | {"status": r["_status"]} for r in rows])
        return
    table([[r["_status"], r["eventType"], r["name"], fmt_range(r["_start"], r["_end"])] for r in rows], ["status", "type", "event", "when (local)"])


def find_event(query: str) -> dict[str, Any]:
    rows = event_rows(live("events"), dt.datetime.now())
    q = norm(query)
    hits = [r for r in rows if q == norm(r["eventID"]) or q == norm(r["name"])] or [r for r in rows if q in norm(r["name"]) or q in norm(r["eventID"])]
    if not hits:
        raise SystemExit(f"pogo: no event matches {query!r}; try `pogo events --all`")
    if len(hits) > 1:
        raise SystemExit("pogo: several events match, pick one by ID: " + ", ".join(r["eventID"] for r in hits))
    return hits[0]


def render_extra(x: Any, indent: int = 1) -> None:
    pad = "  " * indent
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("image", "images", "icon", "link") or (isinstance(v, str) and v.startswith("http")):
                continue
            if isinstance(v, (dict, list)):
                if v:
                    print(f"{pad}{k}:")
                    render_extra(v, indent + 1)
            elif v not in (None, ""):
                print(f"{pad}{k}: {strip_html(v)}")
    elif isinstance(x, list):
        if x and all(isinstance(i, dict) and ("name" in i or "text" in i) and len(i) <= 5 for i in x):
            names = [strip_html(i.get("name") or i.get("text")) + ("*" if i.get("canBeShiny") else "") for i in x]
            print(pad + ", ".join(names))
        else:
            for i in x:
                if isinstance(i, (dict, list)):
                    render_extra(i, indent)
                else:
                    print(f"{pad}- {strip_html(i)}")


def cmd_event(a: argparse.Namespace) -> None:
    r = find_event(a.query)
    if a.json:
        emit_json({k: v for k, v in r.items() if not k.startswith("_")} | {"status": r["_status"]})
        return
    print(f"{r['name']}  [{r['eventType']}, {r['_status']}]")
    print(f"  {fmt_range(r['_start'], r['_end'])}   {r.get('link', '')}")
    if r.get("extraData"):
        render_extra(r["extraData"])
        print("  * = can be shiny")


def raid_rows(raids: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in raids:
        cp = r.get("combatPower") or {}
        n, b = cp.get("normal") or {}, cp.get("boosted") or {}
        out.append({
            "name": r["name"], "tier": r.get("tier", ""), "shiny": bool(r.get("canBeShiny")),
            "types": [t["name"] for t in r.get("types", [])],
            "cp": cp_range(n), "boosted_cp": cp_range(b),
            "weather": [w["name"] for w in r.get("boostedWeather", [])],
        })
    return out


def cmd_raids(a: argparse.Namespace) -> None:
    rows = raid_rows(live("raids"))
    if a.tier:
        rows = [r for r in rows if norm(a.tier) in norm(r["tier"])]
    if a.type:
        rows = [r for r in rows if norm(a.type) in map(norm, r["types"])]
    if a.shiny:
        rows = [r for r in rows if r["shiny"]]
    if a.json:
        emit_json(rows)
        return
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["tier"], []).append(r)
    for tier, rs in groups.items():
        print(tier)
        for r in rs:
            print(f"  {r['name'] + ('*' if r['shiny'] else ''):<32} {'/'.join(r['types']):<16} CP {r['cp']:<10} boosted {r['boosted_cp']:<10} {', '.join(r['weather'])}")
    print("* = can be shiny" if rows else "no matching raid bosses")


def research_rows(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"task": clean(t.get("text")), "rewards": [{"name": rw["name"], "shiny": bool(rw.get("canBeShiny")), "cp": cp_range(rw.get("combatPower"))} for rw in t.get("rewards", [])]} for t in tasks]


def cmd_research(a: argparse.Namespace) -> None:
    rows = research_rows(live("research"))
    if a.query:
        q = norm(a.query)
        rows = [r for r in rows if q in norm(r["task"]) or any(q in norm(x["name"]) for x in r["rewards"])]
    if a.shiny:
        rows = [r for r in rows if any(x["shiny"] for x in r["rewards"])]
    if a.json:
        emit_json(rows)
        return
    for r in rows:
        print(r["task"])
        print("  " + ", ".join(f"{x['name']}{'*' if x['shiny'] else ''} ({x['cp']})" for x in r["rewards"]))
    print("* = can be shiny" if rows else "no matching research tasks")


def cmd_eggs(a: argparse.Namespace) -> None:
    rows = live("eggs")
    if a.km:
        rows = [r for r in rows if norm(r.get("eggType", "")).startswith(norm(str(a.km)) + "km")]
    if a.shiny:
        rows = [r for r in rows if r.get("canBeShiny")]
    if a.regional:
        rows = [r for r in rows if r.get("isRegional")]
    if a.sync:
        rows = [r for r in rows if r.get("isAdventureSync")]
    if a.json:
        emit_json(rows)
        return
    egg = None
    for r in rows:
        label = r.get("eggType", "?") + (" (Adventure Sync)" if r.get("isAdventureSync") else "") + (" (gift)" if r.get("isGiftExchange") else "") + (" (route gift)" if r.get("isRouteGift") else "")
        if label != egg:
            egg = label
            print(egg)
        flags = "regional" if r.get("isRegional") else ""
        print(f"  {r['name'] + ('*' if r.get('canBeShiny') else ''):<28} CP {cp_range(r.get('combatPower')):<11} rarity {r.get('rarity', '?')}  {flags}".rstrip())
    print("* = can be shiny" if rows else "no matching eggs")


def cmd_rocket(a: argparse.Namespace) -> None:
    rows = live("rocket-lineups")
    if a.query:
        q = norm(a.query)
        rows = [r for r in rows if q in norm(r.get("name")) or q in norm(r.get("title")) or q in norm(r.get("type")) or any(q in norm(p.get("name")) for s in r.get("lineups", []) for p in s.get("pokemon", []))]
    if a.shiny:
        rows = [r for r in rows if any(p.get("can_be_shiny") for s in r.get("lineups", []) for p in s.get("pokemon", []))]
    if a.json:
        emit_json(rows)
        return
    for r in rows:
        head = clean(r.get("name") or "?") + (f" ({r['type']}-type grunt)" if r.get("type") else "")
        print(f"{head}  [{clean(r.get('title'))}]")
        if r.get("quote"):
            print(f"  \"{clean(r['quote'])}\"")
        for s in r.get("lineups", []):
            parts = []
            for p in s.get("pokemon", []):
                w = p.get("weaknesses") or {}
                weak = ", ".join([f"{t} x2" for t in w.get("double", [])] + list(w.get("single", [])))
                parts.append(f"{p.get('name')}{'*' if p.get('can_be_shiny') else ''} ({weak})" if weak else str(p.get("name")))
            tag = " [encounter]" if s.get("is_encounter") else ""
            print(f"  slot {s.get('slot')}{tag}: {' / '.join(parts)}")
    print("* = can be shiny; weaknesses in parentheses" if rows else "no matching Team GO Rocket trainers")


def cmd_promos(a: argparse.Namespace) -> None:
    rows = live("promo-codes")
    if a.json:
        emit_json(rows)
        return
    if not rows:
        print("no active promo codes")
    for r in rows:
        print(f"{r.get('code')}  {r.get('title', '')}  (expires {r.get('expiration') or '?'})")
        rewards = r.get("rewards") or []
        if rewards:
            print("  rewards: " + ", ".join(str(x.get("name") or x.get("text") or x) if isinstance(x, dict) else str(x) for x in rewards))
        if r.get("redemption_url"):
            print(f"  {r['redemption_url']}")


def cmd_today(a: argparse.Namespace) -> None:
    now = dt.datetime.now()
    rows = event_rows(live("events"), now)
    active = [r for r in rows if r["_status"] == "NOW"]
    today = [r for r in rows if r["_start"].date() == now.date() and r["_status"] != "ended"]
    raids = raid_rows(live("raids"))
    big = [r for r in raids if any(k in norm(r["tier"]) for k in ("5star", "mega", "shadow", "elite"))]
    promos = live("promo-codes")
    if a.json:
        strip = lambda rs: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rs]
        emit_json({"now": now.isoformat(timespec="minutes"), "active": strip(active), "starting_today": strip(today), "raids": big, "promos": promos})
        return
    print(f"Pokemon Go, {now:%A %b %-d %H:%M}")
    print("Active events")
    for r in active:
        print(f"  {r['name']}  (ends {r['_end']:%a %b %-d %H:%M})")
    if today:
        print("Starting today")
        for r in today:
            print(f"  {fmt_range(r['_start'], r['_end'])}  {r['name']}")
    print("Raid bosses")
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in big:
        groups.setdefault(r["tier"], []).append(r)
    for tier, rs in groups.items():
        print(f"  {tier}: " + ", ".join(x["name"] + ("*" if x["shiny"] else "") for x in rs))
    if promos:
        print("Promo codes: " + ", ".join(str(p.get("code")) for p in promos))
    print("* = can be shiny")


# ---------- PvPoke ----------

def cmd_pvp(a: argparse.Namespace) -> None:
    if a.cups:
        gm = fetch(f"{PVPOKE_URL}/gamemaster.json", REF_TTL)
        rows = [[f["cup"], f["cp"], f["title"]] for f in gm.get("formats", []) if not f.get("hideRankings")]
        if a.json:
            emit_json([{"cup": r[0], "cp": r[1], "title": r[2]} for r in rows])
        else:
            table(rows, ["cup", "cp", "title"])
        return
    if not a.league:
        raise SystemExit("pogo: league is great, ultra, master or little (or --cups)")
    cp = LEAGUES[a.league]
    cup = a.cup or ("little" if a.league == "little" else "all")
    ranks = fetch(f"{PVPOKE_URL}/rankings/{cup}/overall/rankings-{cp}.json", REF_TTL)
    if a.find:
        q = norm(a.find)
        hits = [(i + 1, r) for i, r in enumerate(ranks) if q in norm(r["speciesId"]) or q in norm(r["speciesName"])]
        if not hits:
            raise SystemExit(f"pogo: {a.find!r} is not ranked in {cup} {cp}")
        if a.json:
            emit_json([{"rank": i, **r} for i, r in hits])
            return
        for i, r in hits[:5]:
            print(f"#{i} {r['speciesName']}  score {r.get('score')}  ({cup}, CP {cp})")
            ms = r.get("moveset", [])
            print(f"  Moveset   {title_move(ms[0]) if ms else '?'} + {' / '.join(title_move(m) for m in ms[1:]) or '?'}")
            st = r.get("stats") or {}
            if st:
                print(f"  Stats     product {st.get('product')}  atk {st.get('atk')}  def {st.get('def')}  hp {st.get('hp')}")
            print("  Beats     " + ", ".join(f"{pretty_id(m['opponent'])} ({m['rating']})" for m in r.get("matchups", [])))
            print("  Loses to  " + ", ".join(f"{pretty_id(m['opponent'])} ({m['rating']})" for m in r.get("counters", [])))
            if r.get("editorNotes"):
                print(f"  Notes     {strip_html(r['editorNotes'])}")
        return
    top = ranks[: a.top]
    if a.json:
        emit_json([{"rank": i + 1, "speciesId": r["speciesId"], "name": r["speciesName"], "score": r.get("score"), "moveset": r.get("moveset")} for i, r in enumerate(top)])
        return
    print(f"PvPoke {cup} rankings, CP {cp}")
    table([[i + 1, r["speciesName"], r.get("score"), " + ".join([title_move(r["moveset"][0])] + [" / ".join(title_move(m) for m in r["moveset"][1:])]) if r.get("moveset") else "?"] for i, r in enumerate(top)], ["#", "pokemon", "score", "moveset"])


def cmd_refresh(a: argparse.Namespace) -> None:
    n = 0
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
            n += 1
    print(f"dropped {n} cached file(s) from {CACHE_DIR}")


# ---------- your account: box scans (Poke Genie / Calcy IV) and the official data request ----------
#
# Niantic publishes no player API, so "your data" arrives as files: a Poke Genie or Calcy IV
# CSV of your Pokemon storage (per-Pokemon CP, IVs, moves, league ranks) and the official
# data-request export (account stats, spend, friends, location history, event logs; Pokemon
# by species name only). `pogo inbox` watches the folders those files land in and imports
# them; the `box` and `account` lanes answer questions over the latest import.

DATA_DIR = Path(os.environ.get("POGO_DATA_DIR") or Path(__file__).resolve().parent / "data")
BOX_DIR = DATA_DIR / "box"
ACCOUNT_DIR = DATA_DIR / "account"
IMPORTS = DATA_DIR / "imports.json"
STATE = DATA_DIR / "state.json"
ICLOUD_INBOX = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Pokemon GO"
DEFAULT_INBOXES = [ICLOUD_INBOX, Path.home() / "Downloads"]
NOTIFY = Path(__file__).resolve().parent.parent / "mist-voice/bin/mist-notify"
SETTLE_SECONDS = 10  # a file still being written or synced is left for the next pass

JOURNEY_GROUPS = {
    "encounters": ("map_pokemon_encounter", "incense_encounter", "lure_encounter"),
    "spins": ("pokestop_spin",),
    "raids": ("join_raid_lobby",),
    "gyms": ("gym_battle", "deploy_pokemon", "feed_pokemon"),
    "sessions": ("app_sessions",),
    "go_plus": ("sfida_capture",),
}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_header(h: str) -> str:
    h = h.replace("﻿", "").strip().lower().replace("ø", "o")
    h = re.sub(r"pok[eé]mon", "pokemon", h)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", h).split())


def parse_when(s: Any) -> dt.datetime | None:
    """Timestamps in the exports come in several shapes; return an aware or naive datetime, or None."""
    s = str(s or "").strip()
    if not s or s in ("-", "?"):
        return None
    if re.fullmatch(r"\d{10,13}", s):
        n = int(s)
        return dt.datetime.fromtimestamp(n / 1000 if n > 10**11 else n, tz=dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" UTC", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S %Z", "%d/%m/%Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def month_key(when: dt.datetime) -> str:
    return f"{when:%Y-%m}"


# ---- box: Poke Genie / Calcy IV CSV ----

def sniff_csv(text: str) -> tuple[str, list[list[str]]]:
    """Return (dialect, rows) for a Poke Genie or Calcy IV export; dialect is '' for anything else."""
    text = text.lstrip("﻿")
    sample = text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return "", []
    cols = {norm_header(c) for c in rows[0]}
    genie = sum(k in cols for k in ("atk iv", "def iv", "sta iv", "level min", "shadow purified", "quick move"))
    calcy = sum(k in cols for k in ("unique", "oatt iv", "ancestor", "possiblelevels", "fast move", "special move", "shadowform"))
    if genie >= 3 and genie >= calcy:
        return "pokegenie", rows
    if calcy >= 3:
        return "calcyiv", rows
    return "", rows


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_box_csv(text: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """One record per Pokemon from a Poke Genie or Calcy IV export, header-driven so extra columns are fine."""
    dialect, rows = sniff_csv(text)
    if not dialect:
        return "", [], ["not a Poke Genie or Calcy IV export (header not recognised)"]
    header = [norm_header(c) for c in rows[0]]
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        idx.setdefault(h, i)

    def col(row: list[str], *keys: str) -> str:
        for k in keys:
            i = idx.get(k)
            if i is not None and i < len(row):
                return row[i].strip()
        return ""

    mons: list[dict[str, Any]] = []
    issues: list[str] = []
    for n, row in enumerate(rows[1:], start=2):
        if dialect == "calcyiv" and col(row, "ancestor").lower() in ("1", "true", "yes"):
            continue  # Calcy records the pre-evolution it inferred alongside the real scan
        name = col(row, "name", "pokemon name")
        if not name and not col(row, "pokemon").isdigit():
            name = col(row, "pokemon")
        if not name or name in ("-", "?"):
            issues.append(f"row {n}: no species")
            continue
        cp = _num(col(row, "cp"))
        if cp is None:
            issues.append(f"row {n}: unreadable CP")
            continue
        if dialect == "pokegenie":
            atk, dfn, sta = _num(col(row, "atk iv")), _num(col(row, "def iv")), _num(col(row, "sta iv"))
            lo, hi = _num(col(row, "level min")), _num(col(row, "level max"))
            flag = col(row, "shadow purified")
            shadow, purified, unique = flag == "1", flag == "2", True
            fast = col(row, "quick move")
            charged = [c for c in (col(row, "charge move"), col(row, "charge move 2")) if c]
            lucky, fav = col(row, "lucky") == "1", col(row, "favorite") == "1"
            dex = _num(col(row, "pokemon"))
            ranks = {"great": _num(col(row, "rank g")), "ultra": _num(col(row, "rank u")), "little": _num(col(row, "rank l"))}
            scan = col(row, "scan date", "original scan date")
            if "iv exact" in idx:  # Pogo Lens marks solver guesses; Poke Genie IVs are always exact
                unique = col(row, "iv exact") != "0"
        else:
            atk, dfn, sta = _num(col(row, "oatt iv")), _num(col(row, "odef iv")), _num(col(row, "ohp iv"))
            lo = hi = _num(col(row, "level"))
            unique = col(row, "unique") == "1"
            sf = col(row, "shadowform")
            shadow, purified = sf == "2" or col(row, "shadow") == "1", sf == "3"
            if re.search(r"\bshadow\b", name, re.I):
                shadow, name = True, re.sub(r"\s*\bshadow\b", "", name, flags=re.I).strip()
            fast = col(row, "fast move").strip(" -")
            charged = [c.strip(" -") for c in (col(row, "special move"), col(row, "special move 2")) if c.strip(" -")]
            lucky, fav = col(row, "lucky") == "1", col(row, "favorite", "star") == "1"
            dex = _num(col(row, "nr"))
            ranks = {"great": _num(col(row, "gl rank", "gl rank min")), "ultra": None, "little": _num(col(row, "ll rank min"))}
            scan = col(row, "scan date")
        ivs = [int(v) if v is not None else None for v in (atk, dfn, sta)]
        pct = round(sum(v for v in ivs if v is not None) / 45 * 100, 1) if all(v is not None for v in ivs) else None
        form = col(row, "form")
        gender = {"♂": "m", "♀": "f"}.get(col(row, "gender"), col(row, "gender").lower()[:1])
        nick = col(row, "nickname")
        mons.append({
            "name": name, "form": "" if form in ("", "Normal", "0", "-") else form, "dex": int(dex) if dex else None,
            "nickname": "" if nick in ("-", name) else nick, "gender": gender,
            "cp": int(cp), "hp": int(_num(col(row, "hp")) or 0),
            "atk": ivs[0], "def": ivs[1], "sta": ivs[2], "iv_pct": pct, "iv_exact": unique,
            "level": lo if lo == hi else None, "level_min": lo, "level_max": hi,
            "fast": fast, "charged": charged, "lucky": lucky, "shadow": shadow, "purified": purified,
            "favorite": fav, "rank": {k: int(v) for k, v in ranks.items() if v}, "scanned": scan, "row": n,
            "candy": _num(col(row, "candy")), "candy_xl": _num(col(row, "candy xl")), "caught": col(row, "caught date"),
        })
    return dialect, mons, issues


def record_import(path: Path, kind: str, count: int) -> None:
    imports = read_json(IMPORTS, {})
    imports[sha256_file(path)] = {"file": str(path), "kind": kind, "count": count,
                                  "when": dt.datetime.now().isoformat(timespec="seconds")}
    write_json(IMPORTS, imports)


def import_box(path: Path) -> dict[str, Any]:
    dialect, mons, issues = parse_box_csv(path.read_text(encoding="utf-8", errors="replace"))
    if not dialect:
        raise SystemExit(f"pogo: {path.name}: {issues[0]}")
    snap = {"imported": dt.datetime.now().isoformat(timespec="seconds"), "source": str(path),
            "dialect": dialect, "count": len(mons), "issues": issues, "mons": mons}
    write_json(BOX_DIR / f"{dt.datetime.now():%Y-%m-%dT%H%M%S}.json", snap)
    write_json(BOX_DIR / "latest.json", snap)
    record_import(path, "box", len(mons))
    return snap


def load_box() -> dict[str, Any]:
    snap = read_json(BOX_DIR / "latest.json", None)
    if not snap:
        raise SystemExit("pogo: no box imported yet. Export a CSV from Poke Genie (or Calcy IV) and run `pogo box import <file>`, or drop it in iCloud Drive/Pokemon GO.")
    return snap


def mon_label(m: dict[str, Any]) -> str:
    tags = "".join(t for t, on in (("*", m["shadow"]), ("+", m["purified"]), ("L", m["lucky"]), ("F", m["favorite"])) if on)
    form = f" ({m['form']})" if m["form"] else ""
    nick = f' "{m["nickname"]}"' if m["nickname"] else ""
    return f"{m['name']}{form}{nick}{(' ' + tags) if tags else ''}"


def ivs_label(m: dict[str, Any]) -> str:
    parts = ["?" if v is None else str(v) for v in (m["atk"], m["def"], m["sta"])]
    return "/".join(parts) + ("" if m["iv_exact"] else "~")


def level_label(m: dict[str, Any]) -> str:
    if m["level"] is not None:
        return f"{m['level']:g}"
    if m["level_min"] is not None and m["level_max"] is not None:
        return f"{m['level_min']:g}-{m['level_max']:g}"
    return "?"


def dupe_groups(mons: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Copies of the same species+form+shadow, best first (IV percent, then league rank, then CP)."""
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = {}
    for m in mons:
        groups.setdefault((m["name"], m["form"], m["shadow"]), []).append(m)
    best = lambda m: (-(m["iv_pct"] or 0), min(m["rank"].values()) if m["rank"] else 10**6, -m["cp"])
    return sorted((sorted(g, key=best) for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), g[0]["name"]))


def cmd_box(a: argparse.Namespace) -> None:
    if a.box_cmd == "import":
        snap = import_box(Path(a.file).expanduser())
        print(f"imported {snap['count']} Pokemon from {Path(snap['source']).name} ({snap['dialect']}); {len(snap['issues'])} row(s) skipped")
        return
    snap = load_box()
    mons: list[dict[str, Any]] = snap["mons"]
    if a.box_cmd == "stats":
        pcts = [m["iv_pct"] for m in mons if m["iv_pct"] is not None]
        species = {(m["name"], m["form"]) for m in mons}
        stats = {
            "imported": snap["imported"], "source": snap["source"], "dialect": snap["dialect"],
            "pokemon": len(mons), "species_forms": len(species),
            "hundos": sum(1 for p in pcts if p >= 100), "iv_90_plus": sum(1 for p in pcts if p >= 90),
            "avg_iv": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "shadow": sum(m["shadow"] for m in mons), "purified": sum(m["purified"] for m in mons),
            "lucky": sum(m["lucky"] for m in mons), "favorite": sum(m["favorite"] for m in mons),
            "great_top100": sum(1 for m in mons if m["rank"].get("great", 10**6) <= 100),
            "ultra_top100": sum(1 for m in mons if m["rank"].get("ultra", 10**6) <= 100),
            "little_top100": sum(1 for m in mons if m["rank"].get("little", 10**6) <= 100),
            "duplicate_groups": len(dupe_groups(mons)),
        }
        if a.json:
            emit_json(stats)
            return
        print(f"Box: {stats['pokemon']} Pokemon, {stats['species_forms']} species/forms, scanned {stats['imported'][:16]} ({stats['dialect']})")
        print(f"  IV: {stats['hundos']} hundos, {stats['iv_90_plus']} at 90%+, average {stats['avg_iv']}%")
        print(f"  {stats['shadow']} shadow, {stats['purified']} purified, {stats['lucky']} lucky, {stats['favorite']} favorites")
        print(f"  League rank <= 100: great {stats['great_top100']}, ultra {stats['ultra_top100']}, little {stats['little_top100']}")
        print(f"  {stats['duplicate_groups']} species with more than one copy (pogo box dupes)")
        return
    if a.box_cmd == "dupes":
        groups = dupe_groups(mons)
        if a.json:
            emit_json(groups)
            return
        for g in groups:
            print(f"{mon_label(g[0]).split(' (')[0]}: {len(g)} copies")
            for i, m in enumerate(g):
                keep = "keep " if i < a.keep else "     "
                print(f"  {keep}{mon_label(m):<34} CP {m['cp']:<5} L{level_label(m):<7} {ivs_label(m):<10} {m['iv_pct'] or '?':>5}%  GL#{m['rank'].get('great', '-')}")
        print("* shadow  + purified  L lucky  F favorite  ~ IVs not unique")
        return
    if a.box_cmd == "diff":
        snaps = sorted(p for p in BOX_DIR.glob("*.json") if p.name != "latest.json")
        if len(snaps) < 2:
            raise SystemExit("pogo: need two imports to diff")
        old, new = read_json(snaps[-2], {}), read_json(snaps[-1], {})
        key = lambda m: (m["name"], m["form"], m["cp"], m["hp"], m["atk"], m["def"], m["sta"])
        o, n = {key(m): m for m in old.get("mons", [])}, {key(m): m for m in new.get("mons", [])}
        added, gone = [n[k] for k in n if k not in o], [o[k] for k in o if k not in n]
        if a.json:
            emit_json({"from": old.get("imported"), "to": new.get("imported"), "added": added, "removed": gone})
            return
        print(f"{old.get('imported', '?')[:16]} -> {new.get('imported', '?')[:16]}: +{len(added)} / -{len(gone)}")
        for tag, rows in (("+", added), ("-", gone)):
            for m in rows[:40]:
                print(f"  {tag} {mon_label(m):<34} CP {m['cp']:<5} {ivs_label(m)}")
        return
    # list / find
    rows = mons
    if a.query:
        q = norm(a.query)
        rows = [m for m in rows if q in norm(m["name"]) or q in norm(m["nickname"]) or q in norm(m["form"])]
    if a.min_iv is not None:
        rows = [m for m in rows if (m["iv_pct"] or 0) >= a.min_iv]
    for flag in ("shadow", "lucky", "favorite", "purified"):
        if getattr(a, flag):
            rows = [m for m in rows if m[flag]]
    if a.league:
        rows = [m for m in rows if a.league in m["rank"]]
        rows.sort(key=lambda m: m["rank"][a.league])
    elif a.sort == "cp":
        rows.sort(key=lambda m: -m["cp"])
    elif a.sort == "level":
        rows.sort(key=lambda m: -(m["level_max"] or 0))
    elif a.sort == "name":
        rows.sort(key=lambda m: (m["name"], -m["cp"]))
    else:
        rows.sort(key=lambda m: (-(m["iv_pct"] or -1), -m["cp"]))
    if a.top:
        rows = rows[: a.top]
    if a.json:
        emit_json(rows)
        return
    if not rows:
        print("no Pokemon match")
        return
    table([[mon_label(m), m["cp"], level_label(m), ivs_label(m), f"{m['iv_pct']:g}%" if m["iv_pct"] is not None else "?",
            " + ".join(x for x in [m["fast"], " / ".join(m["charged"])] if x),
            " ".join(f"{k[0].upper()}#{v}" for k, v in sorted(m["rank"].items()))] for m in rows],
          ["pokemon", "cp", "lvl", "ivs", "iv", "moves", "rank"])
    print(f"{len(rows)} shown of {len(mons)} in box (scanned {snap['imported'][:16]}). * shadow + purified L lucky F favorite ~ IVs not unique")


# ---- account: the official data request export ----

def parse_gameplay(text: str) -> dict[str, Any]:
    """Gameplay.txt is free text: labelled lines plus a 'Pokemon in your collection:' list of species names."""
    fields = {
        "start_date": r"Start date:\s*(.+)", "level": r"Level:\s*(\d+)", "total_xp": r"Total XP:\s*(\d+)",
        "pokecoins": r"Pokecoin:\s*(\d+)", "stardust": r"Stardust:\s*(\d+)",
        "distance_km": r"Distance walked:\s*([\d.]+)\s*km", "buddy": r"Buddy nickname:\s*(.+)",
        "trainer_name": r"Pokemon Home Trainer Name:\s*(.+)",
    }
    out: dict[str, Any] = {}
    for k, rx in fields.items():
        m = re.search(rx, text)
        if m:
            v = m.group(1).strip()
            out[k] = float(v) if k == "distance_km" else (int(v) if v.isdigit() else v)
    species: list[str] = []
    start = text.find("Pokemon in your collection:")
    if start >= 0:
        for line in text[start:].splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("You have"):
                break
            line = re.sub(r"\s*\(.*\)$", "", line)
            name = line.split("_POKEMON_")[-1] if "_POKEMON_" in line else line
            species.append(name.title())
    out["pokemon"] = species
    m = re.search(r"You have hatched (\d+)", text)
    out["eggs_hatched"] = int(m.group(1)) if m else None
    m = re.search(r"currently have (\d+) eggs", text)
    out["eggs_held"] = int(m.group(1)) if m else None
    m = re.search(r"You have (\d+) items", text)
    out["items"] = int(m.group(1)) if m else None
    return out


def read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")
    delim = "\t" if path.suffix.lower() == ".tsv" or "\t" in text[:2000] else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        return [], []
    return [norm_header(c) for c in rows[0]], rows[1:]


def time_column(header: list[str]) -> int | None:
    for i, h in enumerate(header):
        if any(w in h for w in ("time", "date", "timestamp")):
            return i
    return None


def summarize_table(path: Path) -> dict[str, Any]:
    """Row count, date range and monthly counts for any TSV/CSV in the export, whatever its columns."""
    header, rows = read_table(path)
    ti = time_column(header)
    months: dict[str, int] = {}
    first = last = None
    if ti is not None:
        for r in rows:
            when = parse_when(r[ti]) if ti < len(r) else None
            if when is None:
                continue
            months[month_key(when)] = months.get(month_key(when), 0) + 1
            first = when if first is None or when < first else first
            last = when if last is None or when > last else last
    return {"file": path.name, "rows": len(rows), "columns": header,
            "first": first.isoformat(timespec="seconds") if first else None,
            "last": last.isoformat(timespec="seconds") if last else None, "months": months}


def summarize_account(files: dict[str, Path]) -> dict[str, Any]:
    summary: dict[str, Any] = {"files": sorted(files), "tables": {}}
    summary["gameplay"] = parse_gameplay(files["Gameplay.txt"].read_text(encoding="utf-8", errors="replace"))
    if "InAppPurchases.tsv" in files:
        header, rows = read_table(files["InAppPurchases.tsv"])
        money = next((i for i, h in enumerate(header) if "money" in h), None)
        cur = next((i for i, h in enumerate(header) if "currency" in h), None)
        coins = next((i for i, h in enumerate(header) if "pokecoin" in h), None)
        ti = time_column(header)
        spend: dict[str, float] = {}
        by_year: dict[str, float] = {}
        coins_spent = coins_bought = 0
        for r in rows:
            amt = _num(r[money]) if money is not None and money < len(r) else None
            c = r[cur].strip() if cur is not None and cur < len(r) else "?"
            if amt:
                spend[c] = round(spend.get(c, 0) + amt, 2)
                when = parse_when(r[ti]) if ti is not None and ti < len(r) else None
                if when:
                    by_year[f"{when:%Y}"] = round(by_year.get(f"{when:%Y}", 0) + amt, 2)
            delta = _num(r[coins]) if coins is not None and coins < len(r) else None
            if delta:
                if delta < 0:
                    coins_spent += int(-delta)
                else:
                    coins_bought += int(delta)
        summary["purchases"] = {"rows": len(rows), "money_by_currency": spend, "money_by_year": by_year,
                                "pokecoins_spent": coins_spent, "pokecoins_bought": coins_bought}
    if "FriendList.tsv" in files:
        header, rows = read_table(files["FriendList.tsv"])
        init = next((i for i, h in enumerate(header) if "initiated" in h), None)
        summary["friends"] = {"count": len(rows),
                              "you_initiated": sum(1 for r in rows if init is not None and init < len(r) and r[init].strip().lower() == "you")}
    if "GameplayLocationHistory.tsv" in files:
        t = summarize_table(files["GameplayLocationHistory.tsv"])
        header, rows = read_table(files["GameplayLocationHistory.tsv"])
        ai = next((i for i, h in enumerate(header) if h.startswith("action")), None)
        actions: dict[str, int] = {}
        for r in rows:
            if ai is not None and ai < len(r):
                actions[r[ai]] = actions.get(r[ai], 0) + 1
        # counts and dates only: the coordinates stay in the file and are never summarised out
        summary["location_history"] = {"points": t["rows"], "first": t["first"], "last": t["last"],
                                       "days": len({m for m in t["months"]}), "top_actions": sorted(actions.items(), key=lambda x: -x[1])[:8]}
    journey: dict[str, dict[str, Any]] = {}
    for name, path in files.items():
        if path.suffix.lower() not in (".csv", ".tsv") or name in ("InAppPurchases.tsv", "FriendList.tsv", "GameplayLocationHistory.tsv"):
            continue
        t = summarize_table(path)
        summary["tables"][name] = {k: v for k, v in t.items() if k != "months"}
        stem = re.sub(r"\d+$", "", name.rsplit(".", 1)[0]).lower()
        for group, prefixes in JOURNEY_GROUPS.items():
            if stem.startswith(prefixes):
                g = journey.setdefault(group, {"rows": 0, "months": {}, "first": None, "last": None})
                g["rows"] += t["rows"]
                for m, c in t["months"].items():
                    g["months"][m] = g["months"].get(m, 0) + c
                g["first"] = min(x for x in (g["first"], t["first"]) if x) if (g["first"] or t["first"]) else None
                g["last"] = max(x for x in (g["last"], t["last"]) if x) if (g["last"] or t["last"]) else None
    summary["journey"] = journey
    return summary


def import_account(src: Path) -> dict[str, Any]:
    stamp = f"{dt.datetime.now():%Y-%m-%dT%H%M%S}"
    dest = ACCOUNT_DIR / stamp
    if src.is_file() and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if info.is_dir() or not str(target).startswith(str(dest.resolve())):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as fh, target.open("wb") as out:
                    shutil.copyfileobj(fh, out)
    elif src.is_dir():
        shutil.copytree(src, dest)
    else:
        raise SystemExit(f"pogo: {src} is neither a zip nor a folder")
    files = {p.name: p for p in dest.rglob("*") if p.is_file()}
    if "Gameplay.txt" not in files:
        shutil.rmtree(dest, ignore_errors=True)
        raise SystemExit(f"pogo: {src.name} has no Gameplay.txt; the Pokemon GO data request export always does")
    summary = summarize_account(files)
    summary["imported"] = dt.datetime.now().isoformat(timespec="seconds")
    summary["source"] = str(src)
    summary["extracted_to"] = str(dest)
    write_json(dest / "summary.json", summary)
    write_json(ACCOUNT_DIR / "summary.json", summary)
    record_import(src, "account", len(files))
    return summary


def load_account() -> dict[str, Any]:
    s = read_json(ACCOUNT_DIR / "summary.json", None)
    if not s:
        raise SystemExit("pogo: no account export imported yet. Request your data in the game's in-app help menu, then `pogo account import <zip>` or drop the zip in iCloud Drive/Pokemon GO.")
    return s


def cmd_account(a: argparse.Namespace) -> None:
    if a.account_cmd == "import":
        s = import_account(Path(a.file).expanduser())
        g = s["gameplay"]
        print(f"imported export from {Path(s['source']).name}: {len(s['files'])} files, trainer level {g.get('level', '?')}, {len(g.get('pokemon', []))} Pokemon listed")
        return
    s = load_account()
    if a.json:
        emit_json(s if a.account_cmd == "show" else s.get("journey") if a.account_cmd == "activity" else s.get("purchases"))
        return
    g = s["gameplay"]
    if a.account_cmd == "show":
        print(f"Trainer {g.get('trainer_name', '?')}  level {g.get('level', '?')}  {g.get('total_xp', '?'):,} XP  since {g.get('start_date', '?')}")
        print(f"  Walked {g.get('distance_km', '?')} km   Stardust {g.get('stardust', '?'):,}   PokeCoins {g.get('pokecoins', '?')}   Buddy {g.get('buddy', '?')}")
        pk = g.get("pokemon", [])
        print(f"  Pokemon in collection: {len(pk)} ({len(set(pk))} species; the export lists species only, no CP or IVs)")
        print(f"  Eggs held {g.get('eggs_held', '?')}, hatched {g.get('eggs_hatched', '?')}   Items {g.get('items', '?')}")
        if "friends" in s:
            print(f"  Friends {s['friends']['count']} ({s['friends']['you_initiated']} you initiated)")
        if "purchases" in s:
            p = s["purchases"]
            money = ", ".join(f"{v:,.2f} {k}" for k, v in p["money_by_currency"].items()) or "none"
            print(f"  Spend {money} over {p['rows']} transactions; PokeCoins bought {p['pokecoins_bought']:,}, spent {p['pokecoins_spent']:,}")
        if "location_history" in s:
            lh = s["location_history"]
            print(f"  Location history: {lh['points']:,} points, {lh['first'][:10] if lh['first'] else '?'} to {lh['last'][:10] if lh['last'] else '?'} (kept in the export folder, never printed)")
        for group, gdata in s.get("journey", {}).items():
            print(f"  {group:<11} {gdata['rows']:>8,} rows  {(gdata['first'] or '?')[:10]} to {(gdata['last'] or '?')[:10]}")
        print(f"  {len(s['files'])} files in the export, imported {s['imported'][:16]}")
        return
    if a.account_cmd == "activity":
        journey = s.get("journey", {})
        months = sorted({m for gdata in journey.values() for m in gdata["months"]})[-a.months:]
        groups = [gname for gname in JOURNEY_GROUPS if gname in journey]
        table([[m] + [journey[gname]["months"].get(m, 0) for gname in groups] for m in months], ["month"] + groups)
        return
    if a.account_cmd == "spend":
        p = s.get("purchases")
        if not p:
            print("no InAppPurchases.tsv in the export")
            return
        table([[y, f"{v:,.2f}"] for y, v in sorted(p["money_by_year"].items())], ["year", "spent"])
        print(f"PokeCoins bought {p['pokecoins_bought']:,}, spent {p['pokecoins_spent']:,}")
        return


# ---- inbox: the launchd-driven importer ----

def classify_export(path: Path) -> str:
    """'box' for a Poke Genie / Calcy CSV, 'account' for the data-request zip, '' otherwise."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
        return "box" if sniff_csv(head)[0] else ""
    if suffix == ".zip" and path.stat().st_size < 2 << 30 and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return "account" if any(n.endswith("Gameplay.txt") for n in z.namelist()) else ""
    return ""


def hydrate_icloud(real: Path, timeout: int = 90) -> bool:
    """Ask iCloud to download an evicted file (the `.name.icloud` placeholder) and wait for it."""
    subprocess.run(["/usr/bin/brctl", "download", str(real)], check=False, capture_output=True)
    deadline = time.time() + timeout
    size = -1
    while time.time() < deadline:
        if real.exists():
            now = real.stat().st_size
            if now == size and now > 0:
                return True
            size = now
        time.sleep(2)
    return real.exists()


def notify(msg: str, link: str = "console", sound: str = "Purr") -> None:
    if NOTIFY.exists():
        subprocess.run([str(NOTIFY), msg, "Pokemon GO", sound, link, "--group", "pokemon-go"], check=False)


def cmd_inbox(a: argparse.Namespace) -> None:
    os.environ["MIST_UNATTENDED"] = "1"  # headless runner; the guard hook covers anything spawned from here
    dirs = [Path(d).expanduser() for d in a.dir] if a.dir else DEFAULT_INBOXES
    if ICLOUD_INBOX in dirs:
        ICLOUD_INBOX.mkdir(parents=True, exist_ok=True)  # shows up in Files on the phone as iCloud Drive/Pokemon GO
    imports = read_json(IMPORTS, {})
    done: list[str] = []
    settling: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.name.startswith(".") and p.name.endswith(".icloud"):
                real = p.with_name(p.name[1:-len(".icloud")])
                if real.suffix.lower() in (".csv", ".zip") and not a.dry_run and hydrate_icloud(real):
                    p = real
                else:
                    continue
            if not p.is_file() or p.suffix.lower() not in (".csv", ".zip"):
                continue
            if time.time() - p.stat().st_mtime < SETTLE_SECONDS:
                settling.append(p)
                continue
            digest = sha256_file(p)
            if digest in imports:
                continue
            kind = classify_export(p)
            if not kind:
                continue
            if a.dry_run:
                done.append(f"would import {kind}: {p}")
                continue
            try:
                if kind == "box":
                    snap = import_box(p)
                    done.append(f"box: {snap['count']} Pokemon from {p.name}")
                else:
                    s = import_account(p)
                    done.append(f"account export: {len(s['files'])} files from {p.name}, level {s['gameplay'].get('level', '?')}")
            except SystemExit as e:
                done.append(f"skipped {p.name}: {e}")
            imports = read_json(IMPORTS, {})
    # A file that was still landing gets one more look, since launchd will not fire again for it.
    if settling and not a.dry_run and not getattr(a, "_retry", False):
        time.sleep(SETTLE_SECONDS + 2)
        a._retry = True
        return cmd_inbox(a)
    stamp = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}]"
    for line in done:
        print(f"{stamp} {line}")
    if done and a.notify and not a.dry_run:
        notify("Pokemon GO: " + "; ".join(done)[:200], "console", "Purr")
    # a box scan goes stale; nudge once a month when the latest one is older than --nudge-days
    state = read_json(STATE, {})
    latest = read_json(BOX_DIR / "latest.json", None)
    age_days = (dt.datetime.now() - dt.datetime.fromisoformat(latest["imported"])).days if latest else None
    last_nudge = parse_when(state.get("last_nudge"))
    if a.notify and age_days is not None and age_days >= a.nudge_days and (last_nudge is None or (dt.datetime.now() - last_nudge).days >= 30):
        notify(f"Your Pokemon GO box scan is {age_days} days old. Scan again and save the CSV to iCloud Drive/Pokemon GO.", "console", "Purr")
        state["last_nudge"] = dt.datetime.now().isoformat(timespec="seconds")
        write_json(STATE, state)
    print(f"{stamp} inbox scan done: {len(done)} action(s), watching {', '.join(str(d) for d in dirs)}")


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pogo", description="Pokemon Go from the terminal.", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Lanes", 1)[1] if __doc__ else None)
    p.add_argument("--no-cache", action="store_true", help="ignore the on-disk cache for this run")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn: Any, help: str, json_flag: bool = True) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        if json_flag:
            sp.add_argument("--json", action="store_true", help="machine-readable output")
        return sp

    add("today", cmd_today, "active events, today's hours, raid bosses, promo codes")
    sp = add("events", cmd_events, "active and upcoming events")
    sp.add_argument("--type", help="filter by event type (community-day, raid-hour, spotlight, go-battle-league, ...)")
    sp.add_argument("--days", type=int, help="only events starting within N days")
    sp.add_argument("--all", action="store_true", help="include ended events")
    sp = add("event", cmd_event, "one event in detail")
    sp.add_argument("query", help="event name or ID")
    sp = add("raids", cmd_raids, "current raid bosses")
    sp.add_argument("--tier", help="1, 3, 5, mega, shadow, ...")
    sp.add_argument("--type", help="Pokemon type")
    sp.add_argument("--shiny", action="store_true")
    sp = add("research", cmd_research, "field research tasks and rewards")
    sp.add_argument("query", nargs="?", help="match task text or reward name")
    sp.add_argument("--shiny", action="store_true")
    sp = add("eggs", cmd_eggs, "egg pools")
    sp.add_argument("--km", type=int, help="2, 5, 7, 10 or 12")
    sp.add_argument("--shiny", action="store_true")
    sp.add_argument("--regional", action="store_true")
    sp.add_argument("--sync", action="store_true", help="Adventure Sync rewards only")
    sp = add("rocket", cmd_rocket, "Team GO Rocket lineups with weaknesses")
    sp.add_argument("query", nargs="?", help="leader, grunt type, or Pokemon")
    sp.add_argument("--shiny", action="store_true", help="only trainers with a possible shiny shadow")
    add("promos", cmd_promos, "active promo codes")
    sp = add("dex", cmd_dex, "Pokedex entry")
    sp.add_argument("name", help="name or dex number")
    sp.add_argument("--form", help="Alola, Galarian, Hisuian, Mega, ...")
    sp.add_argument("--all-forms", action="store_true")
    sp = add("type", cmd_type, "type matchups")
    sp.add_argument("type")
    sp.add_argument("type2", nargs="?")
    sp = add("shiny", cmd_shiny, "where a shiny has been found")
    sp.add_argument("name")
    sp = add("pvp", cmd_pvp, "PvPoke rankings")
    sp.add_argument("league", nargs="?", choices=sorted(LEAGUES))
    sp.add_argument("--cup", help="PvPoke cup slug (see --cups); default all, or little for Little League")
    sp.add_argument("--top", type=int, default=25)
    sp.add_argument("--find", help="show one Pokemon's rank, moveset, wins and losses")
    sp.add_argument("--cups", action="store_true", help="list cups with rankings")
    sp = add("cp", cmd_cp, "CP and HP at a level and IV spread")
    sp.add_argument("name")
    sp.add_argument("--level", required=True, type=float)
    sp.add_argument("--iv", default="15/15/15")
    sp.add_argument("--form")
    sp = add("ivs", cmd_ivs, "IV combinations that fit a CP, HP and dust cost")
    sp.add_argument("name")
    sp.add_argument("--cp", required=True, type=int)
    sp.add_argument("--hp", required=True, type=int)
    sp.add_argument("--dust", type=int, help="stardust cost of the next power-up, as shown in game")
    sp.add_argument("--level", type=float, help="exact level, if known (raids and eggs hatch at 20)")
    sp.add_argument("--form")
    box = sub.add_parser("box", help="your Pokemon storage, from a Poke Genie or Calcy IV CSV export")
    box.set_defaults(fn=cmd_box)
    bs = box.add_subparsers(dest="box_cmd", required=True)
    bi = bs.add_parser("import", help="import a Poke Genie or Calcy IV CSV")
    bi.add_argument("file")
    for name, help_ in (("list", "list and filter the box"), ("find", "alias of list with a query")):
        bl = bs.add_parser(name, help=help_)
        bl.add_argument("query", nargs="?", help="species, nickname or form")
        bl.add_argument("--sort", choices=["iv", "cp", "level", "name"], default="iv")
        bl.add_argument("--min-iv", type=float, help="minimum IV percent")
        bl.add_argument("--league", choices=["great", "ultra", "little"], help="sort by that league rank (Poke Genie/Calcy column)")
        bl.add_argument("--top", type=int)
        for flag in ("shadow", "lucky", "favorite", "purified"):
            bl.add_argument(f"--{flag}", action="store_true")
        bl.add_argument("--json", action="store_true")
    bst = bs.add_parser("stats", help="box summary")
    bst.add_argument("--json", action="store_true")
    bd = bs.add_parser("dupes", help="species with more than one copy, best first")
    bd.add_argument("--keep", type=int, default=1, help="how many of each to mark keep")
    bd.add_argument("--json", action="store_true")
    bdf = bs.add_parser("diff", help="latest import against the one before")
    bdf.add_argument("--json", action="store_true")

    acct = sub.add_parser("account", help="the official data-request export (stats, spend, friends, activity)")
    acct.set_defaults(fn=cmd_account)
    acs = acct.add_subparsers(dest="account_cmd", required=True)
    ai = acs.add_parser("import", help="import the export zip or its unzipped folder")
    ai.add_argument("file")
    for name, help_ in (("show", "trainer stats and what the export holds"), ("spend", "money and PokeCoins by year")):
        ap_ = acs.add_parser(name, help=help_)
        ap_.add_argument("--json", action="store_true")
    aa = acs.add_parser("activity", help="monthly encounters, spins, raids, gym actions, sessions")
    aa.add_argument("--months", type=int, default=24)
    aa.add_argument("--json", action="store_true")

    ib = sub.add_parser("inbox", help="import new exports from iCloud Drive/Pokemon GO and ~/Downloads (launchd runs this)")
    ib.set_defaults(fn=cmd_inbox)
    ib.add_argument("--dir", action="append", help="folder to scan (repeatable; default iCloud Drive/Pokemon GO and ~/Downloads)")
    ib.add_argument("--notify", action="store_true", help="banner on imports and a monthly stale-box nudge")
    ib.add_argument("--nudge-days", type=int, default=30)
    ib.add_argument("--dry-run", action="store_true", help="report what would be imported")

    add("refresh", cmd_refresh, "drop the on-disk cache", json_flag=False)
    return p


def main(argv: list[str] | None = None) -> int:
    global NO_CACHE
    a = build_parser().parse_args(argv)
    NO_CACHE = a.no_cache
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
