"""Screen an ingredient statement for color additives, pigmented ingredients and clouding agents.

Built 2026-11-21 for a "zero-calorie water flavoring with no dyes, completely clear" search, where
"no artificial colors" on the front of a pack was not enough: beet juice, spirulina, caramel and
"vegetable juice (color)" tint the water as much as Red 40 does.

The COLOR terms follow 21 CFR 74 (certified FD&C colors) and 21 CFR 73 (colors exempt from
certification, the "natural" ones). A COLOR hit means the label declares a color additive. TINT
means no declared color, but an ingredient with its own pigment (tea, coffee, a dark fruit juice).
HAZE flags insoluble or emulsified ingredients that can cloud the water without coloring it.

classify(text) -> (verdict, {"color": [...], "tint": [...], "haze": [...]}), verdict one of
COLOR, TINT-RISK, CLEAR, NO-INGREDIENTS. It reads only the text; a label photo is the judge.
"""

from __future__ import annotations

import re

COLOR = [
    r"\bfd ?& ?c\b", r"\bred\s*(no\.?|#)?\s*(40|3)\b", r"\ballura\b", r"\berythrosine\b",
    r"\byellow\s*(no\.?|#)?\s*(5|6)\b", r"\btartrazine\b", r"\bsunset yellow\b",
    r"\bblue\s*(no\.?|#)?\s*(1|2)\b", r"\bbrilliant blue\b", r"\bindigo(tine)?\b",
    r"\bgreen\s*(no\.?|#)?\s*3\b", r"\bfast green\b", r"\bcitrus red\b", r"\borange b\b",
    r"\blakes?\b", r"\bcolou?r(s|ed|ing|ings)?\b", r"\bdyes?\b",
    r"\bannatto\b", r"\bbixin\b", r"\bbeet(root)?s?\b", r"\bbeta[- ]?carotene\b", r"\bcarotenes?\b",
    r"\bcarmine\b", r"\bcochineal\b", r"\bcaramel\b", r"\bcarrots?\b", r"\bpaprika\b",
    r"\bturmeric\b", r"\bcurcumin\b", r"\bsaffron\b", r"\bspirulina\b", r"\btitanium dioxide\b",
    r"\bchlorophyll(in)?\b", r"\biron oxides?\b", r"\banthocyanins?\b", r"\bred cabbage\b",
    r"\bsweet potato\b", r"\bradish\b", r"\bgrape skin\b", r"\benocianina\b", r"\bbutterfly pea\b",
    r"\bsafflower\b", r"\bgardenia\b", r"\bhuito\b", r"\bjagua\b", r"\bgenipin\b", r"\blycopene\b",
    r"\bapocarotenal\b", r"\bcanthaxanthin\b", r"\bastaxanthin\b", r"\blutein\b",
    r"\bvegetable juices?\b", r"\be1[0-8]\d[a-d]?\b",
]
TINT = [
    r"\bteas?\b", r"\bcoffee\b", r"\broasted\b", r"\bbarley\b", r"\bchicory\b", r"\byerba\b",
    r"\bmate\b", r"\bcocoa\b", r"\bcacao\b", r"\bchocolate\b", r"\bmalt\b", r"\bmolasses\b",
    r"\bhibiscus\b", r"\belderberry\b", r"\bacai\b", r"\baronia\b", r"\bcranberr(y|ies)\b",
    r"\bpomegranate\b", r"\bpuree\b", r"\bvanilla extract\b", r"\bginseng\b", r"\bguarana\b",
    r"\briboflavin\b", r"\bvitamin b2\b", r"\bcinnamon\b", r"\bfruit powder\b",
    r"\bpowder(ed)? (fruit|vegetable)\b",
    r"(?<!monk )\b(fruit|vegetable|berry|grape seed|black currant|apple) extracts?\b",
]
HAZE = [
    r"\bgum arabic\b", r"\bgum acacia\b", r"\bacacia\b", r"\bmodified (food|corn) starch\b",
    r"\bglycerol esters? of (wood )?rosin\b", r"\bester gum\b", r"\bsucrose acetate isobutyrate\b",
    r"\bbrominated vegetable oil\b", r"\bcalcium carbonate\b", r"\btricalcium phosphate\b",
    r"\bcalcium silicate\b", r"\bsilicon dioxide\b", r"\bdicalcium phosphate\b",
    r"\bcalcium phosphate\b", r"\blecithin\b", r"\bxanthan\b", r"\bclouding\b", r"\bcloud\b",
    r"\bmagnesium oxide\b", r"\bzinc oxide\b", r"\bcoconut oil\b", r"\bpalm\b", r"\bmct\b",
    r"\bmedium chain triglycerides\b", r"\bmixed triglycerides\b",
]
_COLOR = [re.compile(p, re.I) for p in COLOR]
_TINT = [re.compile(p, re.I) for p in TINT]
_HAZE = [re.compile(p, re.I) for p in HAZE]
# Phrases that contain a color word but declare no color additive.
_NOT_COLOR = re.compile(
    r"\bno (artificial |added )?colou?rs?\b|\bcolou?rless\b|\bclear\b|\bbeet sugar\b"
    r"|\b(to )?(protect|preserve|retain|maintain)s?( flavor and| freshness and)? colou?r\b"
    r"|\bcolou?r retention\b",
    re.I,
)
# Any juice tints the water except pale citrus and white grape.
_JUICE = re.compile(r"((?:[a-z]+[ -]){0,3})juices?\b", re.I)
_PALE_JUICE = re.compile(r"\b(lemon|lime|white grape)\b", re.I)


def _hits(text: str, rxs: list[re.Pattern[str]]) -> list[str]:
    return sorted({m.group(0).lower() for rx in rxs for m in rx.finditer(text)})


def classify(ingredients: str | None) -> tuple[str, dict[str, list[str]]]:
    raw = (ingredients or "").strip()
    text = _NOT_COLOR.sub(" ", raw)
    color = _hits(text, _COLOR)
    tint = set(_hits(text, _TINT))
    for m in _JUICE.finditer(text):
        if not _PALE_JUICE.search(m.group(1)):
            tint.add(m.group(0).lower().strip())
    hits = {"color": color, "tint": sorted(tint), "haze": _hits(text, _HAZE)}
    if not raw:
        return "NO-INGREDIENTS", hits
    if color:
        return "COLOR", hits
    if tint:
        return "TINT-RISK", hits
    return "CLEAR", hits


def describe(ingredients: str | None) -> str:
    """One line for a terminal: the verdict and what drove it."""
    verdict, h = classify(ingredients)
    parts = [verdict]
    if h["color"]:
        parts.append("color: " + ", ".join(h["color"]))
    if h["tint"]:
        parts.append("tint: " + ", ".join(h["tint"]))
    if h["haze"]:
        parts.append("may haze: " + ", ".join(h["haze"]))
    return "  |  ".join(parts)
