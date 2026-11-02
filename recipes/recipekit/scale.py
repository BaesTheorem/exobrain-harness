"""Quantity scaling for ingredient lines, and the leading-quantity split.

scale_text("2 large (250 g) ripe bananas", 1.5) -> "3 large (375 g) ripe bananas"
scale_text("1 (15 oz) can black beans", 2)     -> "2 (15 oz) can black beans"

INVARIANTS:
- Only quantities change. A number that is a size, not an amount, stays: the
  "(15 oz)" in "1 (15 oz) can", a temperature (350°F), a length (9-inch, 23 cm),
  a percentage, and a number glued to letters (V8, 7UP).
- A range or a hyphenated mixed number ("2-3", "1-1/3") scales part by part,
  which is correct for both readings.
- Metric weights and volumes round to whole units (one decimal under 10);
  everything else comes out as a kitchen fraction (1/2, 1/3, 1/4, 1/8) when one
  is within 0.02, else a short decimal.
"""

from __future__ import annotations

import re
from math import gcd

UNICODE_FRACTIONS = {
    "½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅕": 1 / 5, "⅖": 2 / 5,
    "⅗": 3 / 5, "⅘": 4 / 5, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8,
}
_UF = "".join(UNICODE_FRACTIONS)
_NUM = rf"(?:\d+\s+\d+/\d+|\d+\s*[{_UF}]|\d+/\d+|\d+(?:\.\d+)?|[{_UF}])"
QTY_RE = re.compile(rf"(?<![\w.]){_NUM}(?:\s*(?:-|–|to)\s*{_NUM})?(?![\w/])")
NUM_RE = re.compile(_NUM)

UNITS = (
    r"cups?|c\.|tablespoons?|tbsps?\.?|tbs\.?|T\b|teaspoons?|tsps?\.?|t\b|fl\.?\s?oz|fluid ounces?|ounces?|oz\.?|"
    r"pounds?|lbs?\.?|grams?|g\b|kilograms?|kgs?|kg\b|milliliters?|millilitres?|ml|mL|liters?|litres?|l\b|L\b|"
    r"pinch(?:es)?|dash(?:es)?|cloves?|cans?|jars?|packages?|pkgs?\.?|blocks?|sticks?|slices?|bunch(?:es)?|"
    r"sprigs?|handfuls?|heads?|stalks?|scoops?|pieces?|large|medium|small|whole"
)
LEAD_RE = re.compile(rf"^\s*({_NUM}(?:\s*(?:-|–|to)\s*{_NUM})?)(\s*(?:{UNITS})\b\.?)?", re.IGNORECASE)
METRIC_AFTER = re.compile(r"^\s*(?:g|grams?|kg|kilograms?|ml|mL|milliliters?|millilitres?|l|L|liters?|litres?)\b")
SIZE_AFTER = re.compile(r"^\s*(?:°|º|degrees?\b|-?inch(?:es)?\b|in\.|\"|cm\b|mm\b|%|x\s*\d)", re.IGNORECASE)
CONTAINERS = (
    r"cans?|tins?|jars?|packages?|pkgs?|packets?|pouch(?:es)?|boxes|box|bags?|cartons?|blocks?|bottles?|"
    r"containers?|sticks?|tubs?|bars?"
)
SIZE_PAREN = re.compile(rf"\(([^()]*)\)\s*(?:{CONTAINERS})\b", re.IGNORECASE)


def parse_number(s: str) -> float:
    s = s.strip()
    total = 0.0
    for ch, v in UNICODE_FRACTIONS.items():
        if ch in s:
            total += v
            s = s.replace(ch, "").strip()
    if not s:
        return total
    parts = s.split()
    for p in parts:
        if "/" in p:
            a, b = p.split("/", 1)
            total += float(a) / float(b)
        else:
            total += float(p)
    return total


def fmt_number(x: float, metric: bool = False) -> str:
    if metric:
        return str(int(round(x))) if x >= 10 or abs(x - round(x)) < 0.05 else f"{x:.1f}"
    if abs(x - round(x)) < 0.02:
        return str(int(round(x)))
    whole = int(x)
    frac = x - whole
    for den in (2, 3, 4, 8):
        num = round(frac * den)
        if 0 < num < den and abs(frac - num / den) < 0.02:
            g = gcd(num, den)
            fr = f"{num // g}/{den // g}"
            return f"{whole} {fr}" if whole else fr
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _protected_spans(text: str) -> list[tuple[int, int]]:
    return [m.span(1) for m in SIZE_PAREN.finditer(text)]


def scale_text(text: str, factor: float) -> str:
    """Scale every amount in an ingredient line by factor."""
    if factor == 1:
        return text
    protected = _protected_spans(text)
    out: list[str] = []
    pos = 0
    for m in QTY_RE.finditer(text):
        start, end = m.span()
        if any(a <= start < b for a, b in protected) or SIZE_AFTER.match(text[end:]):
            continue
        metric = bool(METRIC_AFTER.match(text[end:]))
        token = m.group(0)
        scaled = NUM_RE.sub(lambda n, metric=metric: fmt_number(parse_number(n.group(0)) * factor, metric), token)
        out.append(text[pos:start] + scaled)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def scale_serves(serves: str, factor: float) -> str:
    """'4' -> '8'; '4 bowls' -> '8 bowls'; '1 loaf (10 slices)' scales both numbers."""
    return scale_text(serves, factor) if serves else serves


def split_quantity(text: str) -> tuple[str, str]:
    """('2 large', ' ripe bananas') for '2 large ripe bananas'; ('', text) if none leads."""
    m = LEAD_RE.match(text)
    if not m or SIZE_AFTER.match(text[m.end(1):]):
        return "", text
    return text[: m.end()], text[m.end():]
