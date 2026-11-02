"""A local index of USDA FoodData Central foods, built from the public bulk files.

The FDC API rate-limits DEMO_KEY after a handful of calls, and a personal key
needs a sign-up. The bulk downloads need neither. This module downloads the
datasets that ingredient-parser matches against (every Foundation release, SR
Legacy, FNDDS survey foods), streams each JSON file one food at a time, and keeps the
fields nutrition.py reads: description, the energy/protein/fat/carbohydrate
values per 100 g, and the household portions.

    python3 -c 'from recipekit import fdcdata; fdcdata.build()'    (or `recipe fdc-update`)

INVARIANTS:
- The index has the same shape as an API /food/{id} response for the fields
  nutrition.py reads, so either source can serve it.
- Memory stays small: foods are decoded one at a time, never the whole file.
- Every Foundation release goes in (each release gives its foods new ids), with
  the newest SR Legacy and survey files; the pinned names are the fallback.
"""

from __future__ import annotations

import io
import json
import os
import re
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("RECIPES_FDC_DATA") or Path.home() / "Library/Caches/exobrain-recipes/fdc-data")
INDEX = ROOT / "index.json"
BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
PAGE = "https://fdc.nal.usda.gov/download-datasets/"
UA = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
PINNED = {
    "foundation": "FoodData_Central_foundation_food_json_2026-10-29.zip",
    "sr_legacy": "FoodData_Central_sr_legacy_food_json_2018-04.zip",
    "survey": "FoodData_Central_survey_food_json_2024-10-31.zip",
}
KEEP_NUTRIENTS = {"203", "204", "205", "208", "298", "957", "958"}
_index: dict[str, Any] | None = None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed https host
        return resp.read()


def releases() -> list[str]:
    """Every Foundation release (FDC gives Foundation foods a new id in each one, and
    ingredient-parser's matches carry ids from an older release), plus the newest
    SR Legacy and survey files. Older ids keep their own records this way."""
    try:
        page = _get(PAGE).decode("utf-8", "replace")
    except OSError:
        return list(PINNED.values())
    out: list[str] = sorted(set(re.findall(r"FoodData_Central_foundation_food_json_[\d-]+\.zip", page)))
    for kind in ("sr_legacy", "survey"):
        names = sorted(set(re.findall(rf"FoodData_Central_{kind}_food_json_[\d-]+\.zip", page)))
        out.append(names[-1] if names else PINNED[kind])
    return out or list(PINNED.values())


def iter_foods(text_stream: io.TextIOBase, chunk: int = 1 << 20) -> Iterator[dict[str, Any]]:
    """Yield each food object of {"<Key>": [ {...}, ... ]} without loading the file."""
    dec = json.JSONDecoder()
    buf = ""
    pos = 0
    started = False
    eof = False
    while True:
        if not started:
            i = buf.find("[", pos)
            if i == -1:
                more = text_stream.read(chunk)
                if not more:
                    return
                buf += more
                continue
            pos, started = i + 1, True
        while pos < len(buf) and buf[pos] in " \t\r\n,":
            pos += 1
        if pos < len(buf) and buf[pos] == "]":
            return
        try:
            obj, end = dec.raw_decode(buf, pos)
        except ValueError:
            if eof:
                return
            more = text_stream.read(chunk)
            if not more:
                eof = True
            buf = buf[pos:] + more
            pos = 0
            continue
        yield obj
        pos = end
        if pos > chunk:
            buf, pos = buf[pos:], 0


def slim(food: dict[str, Any]) -> dict[str, Any]:
    nutrients = []
    for n in food.get("foodNutrients") or []:
        nu = n.get("nutrient") or {}
        if str(nu.get("number")) in KEEP_NUTRIENTS and n.get("amount") is not None:
            nutrients.append({"nutrient": {"number": str(nu["number"]), "unitName": nu.get("unitName")},
                              "amount": n["amount"]})
    portions = []
    for p in food.get("foodPortions") or []:
        portions.append({k: p.get(k) for k in ("amount", "gramWeight", "modifier", "portionDescription")
                         if p.get(k) not in (None, "")} | {"measureUnit": {"name": (p.get("measureUnit") or {}).get("name")}})
    return {"description": food.get("description"), "dataType": food.get("dataType"),
            "foodNutrients": nutrients, "foodPortions": portions}


def build(progress=print) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {}
    for name in releases():
        kind = name.removeprefix("FoodData_Central_").split("_food_json_")[0]
        raw = ROOT / name
        if not raw.exists():
            progress(f"downloading {name}")
            raw.write_bytes(_get(BASE + name))
        with zipfile.ZipFile(raw) as z:
            member = next(m for m in z.namelist() if m.endswith(".json"))
            with z.open(member) as fh:
                count = 0
                for food in iter_foods(io.TextIOWrapper(fh, encoding="utf-8")):
                    if isinstance(food, dict) and "fdcId" in food:   # the 2026-04-30 file holds 32 nulls
                        index[str(food["fdcId"])] = slim(food)
                        count += 1
        progress(f"{name}: {count} foods ({kind})")
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, separators=(",", ":")))
    tmp.replace(INDEX)
    global _index
    _index = index
    return INDEX


def _load() -> dict[str, Any]:
    global _index
    if _index is None:
        _index = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    return _index or {}


def lookup(fdc_id: int, description: str = "") -> dict[str, Any] | None:
    """A food by id; by exact description when the id is from a release we lack."""
    index = _load()
    food = index.get(str(int(fdc_id)))
    if food is None and description:
        key = description.strip().lower()
        food = next((f for f in index.values() if str(f.get("description") or "").lower() == key), None)
    return food
