"""A recipe from a URL, through the schema.org/Recipe JSON-LD in the page.

recipe-scrapers (hhursev, MIT) reads the page; ld_ingredient_count() reads the
raw JSON-LD a second, independent way, so an import can prove that no
ingredient line was lost on the way into the note.

INVARIANTS:
- The import never invents a Cooking for Engineers tree. That step needs
  judgment, so the note arrives with status to-try and no cfe, and MIST writes
  the tree through /recipes.
- A field the page does not have stays out of the frontmatter.
"""

from __future__ import annotations

import html as htmllib
import json
import re
import urllib.request
from typing import Any

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
_LD_RE = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)
COURSES = {
    "breakfast": "breakfast", "brunch": "breakfast", "dessert": "dessert", "desserts": "dessert", "drink": "drink",
    "drinks": "drink", "beverage": "drink", "cocktail": "drink", "side": "side", "side dish": "side",
    "appetizer": "snack", "snack": "snack", "sauce": "sauce", "condiment": "sauce", "dressing": "sauce",
    "soup": "soup", "salad": "salad", "bread": "bread", "main": "main", "main course": "main", "dinner": "main",
    "lunch": "main", "entree": "main",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - a URL Alex gave
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _recipes_in(obj: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(obj, list):
        for x in obj:
            out += _recipes_in(x)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Recipe" in types:
            out.append(obj)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in obj:
                out += _recipes_in(obj[key])
    return out


def ld_recipes(page: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for block in _LD_RE.findall(page):
        text = block.strip()
        for candidate in (text, htmllib.unescape(text)):
            try:
                found += _recipes_in(json.loads(candidate))
                break
            except ValueError:
                continue
    return found


def ld_ingredient_count(page: str) -> int | None:
    recipes = ld_recipes(page)
    if not recipes:
        return None
    ing = recipes[0].get("recipeIngredient") or recipes[0].get("ingredients") or []
    return len(ing) if isinstance(ing, list) else None


def _try(fn, default=None):
    try:
        v = fn()
    except Exception:  # noqa: BLE001 - recipe-scrapers raises a different class per missing field
        return default
    return default if v in (None, "", []) else v


def _minutes(v: Any) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _text(fragment: str) -> str:
    text = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())
    text = re.sub(r"\s+([,.;:)])", r"\1", text.replace("( ", "("))
    return text.lstrip("▢☐ ").strip()


class WprmPage:
    """The recipe-scrapers interface over WP Recipe Maker's HTML, for a page with no JSON-LD.

    WP Recipe Maker is the most common recipe plugin on food blogs; some
    installs render the card but leave the schema.org block out.
    """

    def __init__(self, page: str, url: str):
        self.page, self.url = page, url

    def _first(self, cls: str) -> str:
        m = re.search(rf'<[^>]+class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</(?:h\d|span|div)>', self.page, re.S)
        return _text(m.group(1)) if m else ""

    def title(self) -> str:
        return self._first("wprm-recipe-name")

    def ingredients(self) -> list[str]:
        items = re.findall(r'<li[^>]+class="[^"]*\bwprm-recipe-ingredient\b[^"]*"[^>]*>(.*?)</li>', self.page, re.S)
        return [t for t in (_text(x) for x in items) if t]

    def ingredient_groups(self) -> list[Any]:
        return []

    def instructions_list(self) -> list[str]:
        items = re.findall(r'<div[^>]+class="[^"]*\bwprm-recipe-instruction-text\b[^"]*"[^>]*>(.*?)</div>', self.page, re.S)
        return [t for t in (_text(x) for x in items) if t]

    def yields(self) -> str:
        m = re.search(r'class="[^"]*\bwprm-recipe-servings\b[^"]*"[^>]*>\s*(\d+)', self.page)
        return m.group(1) if m else ""

    def _minutes(self, kind: str) -> int | None:
        h = re.search(rf'wprm-recipe-{kind}_time-hours[^>]*>(\d+)', self.page)
        m = re.search(rf'wprm-recipe-{kind}_time-minutes[^>]*>(\d+)', self.page)
        total = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
        return total or None

    def prep_time(self):
        return self._minutes("prep")

    def cook_time(self):
        return self._minutes("cook")

    def total_time(self):
        return self._minutes("total")

    def canonical_url(self) -> str:
        return self.url

    def author(self) -> str:
        return self._first("wprm-recipe-author")

    def image(self) -> str:
        m = re.search(r'<meta property="og:image" content="([^"]+)"', self.page)
        return m.group(1) if m else ""

    def cuisine(self) -> str:
        return self._first("wprm-recipe-cuisine")

    def category(self) -> str:
        return self._first("wprm-recipe-course")

    def description(self) -> str:
        return self._first("wprm-recipe-summary")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9/]+", " ", htmllib.unescape(str(text)).lower()).strip()


def regroup(groups: list[tuple[str | None, list[str]]], flat: list[str]) -> list[Any]:
    """The ingredient list with its groups, where the items are exactly `flat`.

    `flat` is the publisher's own list (JSON-LD). recipe-scrapers builds groups by
    matching each HTML group line to an ingredient by similarity, and a long note
    can pull the wrong line: a key lime pie page got its cashews twice and lost
    the coconut cream. So a group's items are trusted only when they equal the
    flat list. Otherwise only the group sizes are used, to cut the flat list,
    and with no usable sizes the list stays flat.
    """
    named = [name for name, _ in groups if name]
    if len(groups) < 2 or not named:
        return list(flat)
    items = [x for _, g in groups for x in g]
    if sorted(map(_norm, items)) == sorted(map(_norm, flat)):
        cut = [g for _, g in groups]
    elif len(items) == len(flat):
        cut, k = [], 0
        for _, g in groups:
            cut.append(flat[k : k + len(g)])
            k += len(g)
    else:
        return list(flat)
    out: list[Any] = []
    for (name, _), part in zip(groups, cut, strict=True):
        if name:
            out.append({"group": name, "items": list(part)})
        else:
            out.extend(part)
    return out


def from_page(page: str, url: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    """(frontmatter, data, description, report) for one recipe page."""
    from recipe_scrapers import scrape_html  # lazy: a CLI dependency

    try:
        s: Any = scrape_html(page, org_url=url, supported_only=False)
    except Exception:  # noqa: BLE001 - NoSchemaFoundInWildMode and kin: try the plugin's HTML
        if "wprm-recipe-ingredient" not in page:
            raise
        s = WprmPage(page, url)
    title = _try(s.title, "Imported recipe")
    ld = ld_recipes(page)
    ld_lines = ld[0].get("recipeIngredient") if ld else None
    flat = ([_text(str(x)) for x in ld_lines] if isinstance(ld_lines, list) and ld_lines
            else [str(x) for x in _try(s.ingredients, []) or []])
    groups = [(getattr(g, "purpose", None), list(getattr(g, "ingredients", []) or []))
              for g in _try(s.ingredient_groups, []) or []]
    ingredients = regroup(groups, flat)
    steps = [str(x).strip() for x in _try(s.instructions_list, []) or [] if str(x).strip()]
    yields = str(_try(s.yields, "") or "")
    m = re.match(r"\s*(\d+)", yields)
    category = str(_try(s.category, "") or "").split(",")[0].strip().lower()
    fm: dict[str, Any] = {
        "type": "recipe",
        "title": title,
        "course": COURSES.get(category),
        "cuisine": (str(_try(s.cuisine, "") or "").split(",")[0].strip() or None),
        "status": "to-try",
        "servings": int(m.group(1)) if m else None,
        "yield": yields or None,
        "prep_min": _minutes(_try(s.prep_time)),
        "cook_min": _minutes(_try(s.cook_time)),
        "total_min": _minutes(_try(s.total_time)),
        "source": _try(s.canonical_url, url) or url,
        "author": _try(s.author),
        "image": _try(s.image),
        "tags": ["recipe"],
    }
    data = {"ingredients": ingredients, "steps": steps}
    from .model import flatten

    expected = ld_ingredient_count(page)
    got = flatten(ingredients)
    same = ld_lines is None or [_norm(x) for x in got] == [_norm(x) for x in ld_lines]
    report = {"ingredients": len(got), "json_ld_ingredients": expected,
              "steps": len(steps), "match": (expected is None or expected == len(got)) and same}
    return {k: v for k, v in fm.items() if v is not None}, data, str(_try(s.description, "") or ""), report
