"""kcal and protein per serving from USDA FoodData Central (FDC).

For each ingredient line:
1. ingredient-parser (strangetom, MIT) splits the line into amounts and a name
   and matches the name to an FDC food offline (``foundation_foods=True``).
2. FDC gives that food's nutrients per 100 g and its household portions:
   from the local bulk index (fdcdata.py, built once by `recipe fdc-update`),
   else from the API (FDC_API_KEY, else DEMO_KEY, which rate-limits fast).
3. Grams come from a mass amount on the line ("(250 g)"), else a size times a
   count ("1 (15 oz) can"), else a volume times a density from the food's own
   portions, else a count times a portion weight. A weight that rests on a
   guess carries the flag "est.".
4. Overrides in the data block's "nutrition" map, keyed by ingredient index,
   win over every step:
       {"fdc_id": 123}             use this FDC food
       {"grams": 120}              use this weight
       {"kcal": 400, "protein": 40}    label values for the whole line
       {"skip": true}              count zero (water, salt to taste)

INVARIANTS:
- A line with no match and no override counts zero and is flagged "no match".
  It is never guessed, and the summary says how many lines are open.
- Energy is the reported kcal (nutrient 208, else the Atwater-factor values
  957/958). If a record has none, energy is 4/9/4 kcal per gram of protein,
  fat and carbohydrate, flagged "Atwater".
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any

CACHE = Path(os.environ.get("RECIPES_FDC_CACHE") or Path.home() / "Library/Caches/exobrain-recipes/fdc")
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
FDC_URL = "https://api.nal.usda.gov/fdc/v1/food/{id}?api_key={key}"
FDC_PAGE = "https://fdc.nal.usda.gov/food-details/{id}/nutrients"

MASS_G = {"gram": 1.0, "kilogram": 1000.0, "milligram": 0.001, "ounce": 28.3495, "pound": 453.592}
VOLUME_ML = {
    "milliliter": 1.0, "liter": 1000.0, "teaspoon": 4.92892, "tablespoon": 14.7868, "cup": 236.588,
    "fluid_ounce": 29.5735, "pint": 473.176, "quart": 946.353, "gallon": 3785.41, "deciliter": 100.0,
}
_VOL_WORDS = {
    "cup": "cup", "cups": "cup", "c": "cup", "tbsp": "tablespoon", "tbsps": "tablespoon", "tablespoon": "tablespoon",
    "tablespoons": "tablespoon", "tsp": "teaspoon", "tsps": "teaspoon", "teaspoon": "teaspoon",
    "teaspoons": "teaspoon", "fl oz": "fluid_ounce", "milliliter": "milliliter", "milliliters": "milliliter",
    "ml": "milliliter", "liter": "liter", "liters": "liter", "l": "liter",
}
_VOL_RE = re.compile(r"^\s*(?:(\d+(?:\.\d+)?|\d+/\d+)\s*)?(fl oz|cups?|c|tbsps?|tablespoons?|tsps?|teaspoons?|"
                     r"milliliters?|ml|liters?|l)\b")
SIZE_WORDS = ("small", "medium", "large", "extra large", "jumbo")


# ---------- FDC ----------

class FdcUnavailable(RuntimeError):
    pass


def fdc_food(fdc_id: int, fetch=None, description: str = "") -> dict[str, Any]:
    """One food: the local bulk index first (fdcdata), then the per-food cache, then the API."""
    from . import fdcdata

    local = fdcdata.lookup(fdc_id, description)
    if local is not None:
        return local
    path = CACHE / f"{int(fdc_id)}.json"
    if path.exists():
        return json.loads(path.read_text())
    key = os.environ.get("FDC_API_KEY") or "DEMO_KEY"
    if fetch is None:
        req = urllib.request.Request(FDC_URL.format(id=int(fdc_id), key=key), headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
                data = json.load(resp)
        except OSError as e:
            raise FdcUnavailable(f"FDC food {fdc_id} is not in the local index and the API said: {e}") from e
    else:
        data = fetch(int(fdc_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def _nutrient(food: dict[str, Any], *numbers: str) -> float | None:
    found: dict[str, float] = {}
    for n in food.get("foodNutrients") or []:
        nu = n.get("nutrient") or {}
        num = str(nu.get("number") or n.get("nutrientNumber") or "")
        amount = n.get("amount", n.get("value"))
        unit = str(nu.get("unitName") or n.get("unitName") or "").lower()
        if num in numbers and amount is not None and (num not in ("208", "957", "958") or unit == "kcal"):
            found.setdefault(num, float(amount))
    return next((found[n] for n in numbers if n in found), None)


def per_100g(food: dict[str, Any]) -> tuple[float, float, list[str]]:
    """(kcal, protein g) per 100 g, and flags."""
    protein = _nutrient(food, "203") or 0.0
    kcal = _nutrient(food, "208", "958", "957")
    if kcal is not None:
        return kcal, protein, []
    fat = _nutrient(food, "204", "298") or 0.0
    carbs = _nutrient(food, "205", "205.2") or 0.0
    kcal = 4 * protein + 9 * fat + 4 * carbs
    return kcal, protein, (["Atwater"] if kcal else [])


_FILLER = {"fresh", "large", "medium", "small", "chopped", "diced", "minced", "sliced", "ground", "whole", "raw",
           "dried", "dry", "organic", "fine", "finely", "extra", "plain", "unsalted", "salted", "cold", "warm",
           "hot", "softened", "melted", "packed", "heaping", "level", "and", "or", "of", "the", "a", "for"}


def _stem(w: str) -> str:
    w = w.lower().strip(".,()'\"")
    for suf in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def suspicious(name: str, match: str) -> bool:
    """True when a content word of the ingredient name is missing from the FDC description."""
    want = {_stem(w) for w in re.split(r"[\s,/-]+", name) if len(w) > 2 and w.lower() not in _FILLER}
    have = {_stem(w) for w in re.split(r"[\s,/-]+", match) if w}
    return bool(want) and not want <= have


def _portion(p: dict[str, Any]) -> tuple[str, float, str] | None:
    """("volume", grams per ml, "") or ("count", grams per item, label text)."""
    grams = p.get("gramWeight")
    if not grams:
        return None
    unit = str((p.get("measureUnit") or {}).get("name") or "").lower()
    mod = str(p.get("modifier") or "").lower()
    desc = str(p.get("portionDescription") or "").lower()
    amount = p.get("amount")
    for text in (unit, mod, desc):
        m = _VOL_RE.match(text)
        if m:
            n = float(Fraction(m.group(1))) if m.group(1) else 1.0
            qty = float(amount) if amount else n
            ml = qty * VOLUME_ML[_VOL_WORDS[m.group(2)]]
            return ("volume", float(grams) / ml, "") if ml else None
    if "quantity not specified" in desc:
        return ("count", float(grams) / float(amount or 1), "default")
    label = " ".join(x for x in (unit if unit != "undetermined" else "", mod, desc) if x)
    return ("count", float(grams) / float(amount or 1), label)


def density(food: dict[str, Any]) -> float | None:
    vols = [x for p in food.get("foodPortions") or [] if (x := _portion(p)) and x[0] == "volume"]
    return vols[0][1] if vols else None


def item_grams(food: dict[str, Any], line: str) -> tuple[float, bool] | None:
    """(grams per item, exact) for a count; exact is False for the default portion."""
    counts = [x for p in food.get("foodPortions") or [] if (x := _portion(p)) and x[0] == "count"]
    if not counts:
        return None
    low = line.lower()
    size = next((w for w in SIZE_WORDS if re.search(rf"\b{w}\b", low)), None)
    if size:
        hit = next((c for c in counts if size in c[2]), None)
        if hit:
            return hit[1], True
    named = [c for c in counts if c[2] and c[2] != "default"]
    if named:
        # "1/2 lemon" means half the fruit, not half of a "1 slice or wedge" portion
        whole = [c for c in named if re.search(r"\b(?:medium|fruit|whole|each)\b", c[2])]
        parts = re.compile(r"\b(?:slices?|wedges?|pieces?|leaf|leaves|sprigs?|stalks?|strips?|cubes?|chopped|diced|sliced)\b")
        plain = [c for c in named if not parts.search(c[2])]
        pick = (sorted(whole, key=lambda c: "medium" not in c[2]) or plain or named)[0]
        return pick[1], bool(whole) and not size
    return counts[0][1], False


# ---------- parsing a line ----------

def _qty(a: Any) -> float | None:
    try:
        q = float(Fraction(str(a.quantity))) if not isinstance(a.quantity, (int, float)) else float(a.quantity)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    hi = getattr(a, "quantity_max", None)
    if getattr(a, "RANGE", False) and hi not in (None, a.quantity):
        try:
            q = (q + float(Fraction(str(hi)))) / 2
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return q


def _kind(a: Any) -> tuple[str, float]:
    name = str(getattr(a, "unit", "") or "").strip().lower().replace(" ", "_")
    if name in MASS_G:
        return "mass", MASS_G[name]
    if name in VOLUME_ML:
        return "volume", VOLUME_ML[name]
    return "count", 1.0


def parse(line: str) -> tuple[list[Any], int | None, str, str]:
    """(amounts, matched fdc id or None, matched description, parsed name) through ingredient-parser."""
    from ingredient_parser import parse_ingredient  # lazy: a CLI dependency

    r = parse_ingredient(line, foundation_foods=True)
    ff = list(getattr(r, "foundation_foods", None) or [])
    names = r.name if isinstance(r.name, list) else [r.name]
    name = " ".join(n.text for n in names if n is not None)
    return list(r.amount or []), (ff[0].fdc_id if ff else None), (ff[0].text if ff else ""), name


def _measure(a: Any) -> tuple[str, float] | None:
    """(kind, quantity in g / ml / items); a composite ("2 1/4 cups + 6 tbsp") sums its parts."""
    parts = getattr(a, "amounts", None)
    if parts:
        ms = [_measure(p) for p in parts]
        if all(ms) and len({m[0] for m in ms if m}) == 1:
            return ms[0][0], sum(m[1] for m in ms if m)  # type: ignore[index]
        return None
    q = _qty(a)
    if q is None:
        return None
    kind, factor = _kind(a)
    return kind, q * factor


def line_grams(line: str, amounts: list[Any], food: dict[str, Any] | None) -> tuple[float | None, list[str]]:
    meas = [(a, _measure(a)) for a in amounts]
    mass = [m for a, m in meas if m and m[0] == "mass" and not getattr(a, "SINGULAR", False)]
    if mass:
        return mass[0][1], []
    size = [m for a, m in meas if m and m[0] == "mass" and getattr(a, "SINGULAR", False)]
    counts = [m for a, m in meas if m and m[0] == "count"]
    if size and counts:
        return counts[0][1] * size[0][1], []
    vol = [m for a, m in meas if m and m[0] == "volume"]
    if vol:
        ml = vol[0][1]
        d = density(food) if food else None
        return (ml * d, []) if d else (ml, ["est."])
    if counts and food:
        per = item_grams(food, line)
        if per:
            return counts[0][1] * per[0], ([] if per[1] else ["est."])
    return None, ["no amount"] if not amounts else ["no weight"]


# ---------- a recipe ----------

def compute(ingredients: list[str], overrides: dict[str, Any] | None = None, servings: float = 1.0,
            parse_line=parse, food_of=fdc_food) -> dict[str, Any]:
    overrides = overrides or {}
    rows = []
    for i, line in enumerate(ingredients):
        ov = overrides.get(str(i)) or overrides.get(i) or {}  # type: ignore[call-overload]
        row: dict[str, Any] = {"i": i, "line": line, "fdc_id": None, "match": "", "grams": None,
                               "kcal": 0.0, "protein": 0.0, "flags": []}
        if ov.get("skip"):
            row["flags"] = ["skipped"]
            rows.append(row)
            continue
        if "kcal" in ov:
            row.update(kcal=float(ov["kcal"]), protein=float(ov.get("protein", 0.0)), match="label (override)",
                       grams=ov.get("grams"))
            rows.append(row)
            continue
        amounts, fdc_id, desc, name = parse_line(line)
        chosen = bool(ov.get("fdc_id"))
        if chosen:
            fdc_id, desc = int(ov["fdc_id"]), ""
        if not fdc_id:
            row["flags"] = ["no match"]
            rows.append(row)
            continue
        food = food_of(fdc_id, description=desc)
        row["fdc_id"], row["match"] = fdc_id, str(food.get("description") or desc)
        grams, flags = (float(ov["grams"]), []) if ov.get("grams") else line_grams(line, amounts, food)
        kcal100, prot100, nflags = per_100g(food)
        check = ["check match"] if not chosen and suspicious(name, row["match"]) else []
        row["flags"] = flags + nflags + check
        if grams is not None:
            row.update(grams=grams, kcal=grams / 100 * kcal100, protein=grams / 100 * prot100)
        rows.append(row)
    total_k = sum(r["kcal"] for r in rows)
    total_p = sum(r["protein"] for r in rows)
    servings = servings if servings and servings > 0 else 1.0
    open_lines = sum(1 for r in rows if {"no match", "no weight", "check match"} & set(r["flags"]))
    return {"rows": rows, "total": {"kcal": total_k, "protein": total_p}, "servings": servings,
            "per_serving": {"kcal": total_k / servings, "protein": total_p / servings}, "open": open_lines,
            "estimates": sum(1 for r in rows if "est." in r["flags"])}


def markdown(result: dict[str, Any]) -> str:
    ps = result["per_serving"]
    n = result["servings"]
    head = f"Per serving ({n:g} serving{'s' if n != 1 else ''}): **{ps['kcal']:.0f} kcal, {ps['protein']:.1f} g protein**."
    notes = []
    if result["estimates"]:
        notes.append(f"{result['estimates']} line{'s are' if result['estimates'] != 1 else ' is'} an estimate (est.)")
    if result["open"]:
        notes.append(f"{result['open']} line{'s need' if result['open'] != 1 else ' needs'} a check (no match, no weight, or a doubtful match)")
    lines = [head + (" " + "; ".join(notes).capitalize() + "." if notes else ""), "",
             "| # | Ingredient | USDA match | g | kcal | Protein g | Check |", "| -: | --- | --- | -: | -: | -: | --- |"]
    for r in result["rows"]:
        match = f"[{r['match']}]({FDC_PAGE.format(id=r['fdc_id'])})" if r["fdc_id"] else r["match"]
        grams = f"{r['grams']:.0f}" if isinstance(r["grams"], (int, float)) else ""
        cells = [str(r["i"]), r["line"].replace("|", "/"), match.replace("|", "/"), grams,
                 f"{r['kcal']:.0f}", f"{r['protein']:.1f}", ", ".join(r["flags"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Source: USDA FoodData Central. ingredient-parser picks each match; a \"nutrition\" override in "
              "the data block changes one."]
    return "\n".join(lines)
