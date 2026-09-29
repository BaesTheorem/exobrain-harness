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
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
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
