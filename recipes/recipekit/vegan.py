"""Animal-product check for ingredient lines, bivalve-inclusive.

The screen follows a bivalve-inclusive vegan diet: no meat, finfish,
crustaceans, dairy, eggs or honey, but bivalves (oysters, mussels, clams,
scallops, cockles) pass, so oyster sauce passes.
This is a keyword screen that finds candidates for MIST to judge and swap. It
is not a certification: a branded item can hide an animal product (natural
flavors, some sugars, wine fining), and the screen cannot see that.

INVARIANTS:
- A plant form of a flagged word passes: peanut butter, coconut milk, vegan
  cheese, eggplant, cream of tartar, butter beans, dandelion honey.
- Matching is whole-word and case-insensitive.
"""

from __future__ import annotations

import re

FLAGS: dict[str, str] = {
    r"beef|steak|veal|pork|bacon|ham|prosciutto|pancetta|salami|pepperoni|chorizo|sausages?|lamb|mutton|"
    r"venison|bison|goat meat|chicken|turkey|duck|goose|lard|tallow|suet|bone broth|gelatine?|"
    r"chicken (?:stock|broth)|beef (?:stock|broth)": "meat",
    r"fish|salmon|tuna|cod|halibut|tilapia|trout|sardines?|anchov(?:y|ies)|mackerel|bonito|dashi|"
    r"fish sauce|worcestershire": "fish",
    r"shrimp|prawns?|crabs?|lobsters?|crawfish|crayfish|squid|calamari|octopus": "crustacean or cephalopod",
    r"milk|buttermilk|butter|ghee|cream|half[- ]and[- ]half|creme fraiche|crème fraîche|sour cream|cheese|parmesan|"
    r"parmigiano|mozzarella|cheddar|ricotta|feta|mascarpone|paneer|yogh?urt|whey|casein|custard": "dairy",
    r"eggs?|egg whites?|egg yolks?|yolks?|mayonnaise|mayo|meringue|aioli": "egg",
    r"honey": "honey",
}

PLANT = re.compile(
    r"\b(?:vegan|plant[- ]based|plant|non-?dairy|dairy-free|egg-free|vegetarian|"
    r"soy|oat|almond|cashew|coconut|rice|hemp|pea|peanut|nut|seed|sunflower|apple|pumpkin|cocoa|shea|"
    r"flax|chia|aquafaba|just|dandelion|bee-free|mushroom)\s+(?:\w+\s+)?"
    r"(?:milk|butter|cream|cheese|yogh?urt|egg|eggs|mayo|mayonnaise|honey|fish sauce|sauce|worcestershire|"
    r"bacon|sausages?|chicken|beef|broth|stock)\b"
    r"|\beggplants?\b|\bcream of tartar\b|\bbutter(?:nut| beans?|head| lettuce)\b|\bbutterscotch\b|"
    r"\bhoneydew\b|\bcoconut cream\b|\bcashew cream\b|\bice cream\b(?=.*\bvegan\b)|\bnutritional yeast\b|"
    r"\bmilk thistle\b|\bmilk chocolate\b(?=.*\b(?:vegan|dairy-free)\b)|\bnut cheese\b|\bsoy curls?\b|"
    r"\bvegetable (?:stock|broth)\b|\bmock\s+\w+\b|\bfish-free\b|\bkelp\b",
    re.IGNORECASE,
)
BIVALVES = re.compile(r"\b(?:oysters?|oyster sauce|mussels?|clams?|clam juice|scallops?|cockles?)\b", re.IGNORECASE)
_FLAG_RES = [(re.compile(rf"\b(?:{pat})\b", re.IGNORECASE), why) for pat, why in FLAGS.items()]


def check(line: str) -> list[tuple[str, str]]:
    """[(matched word, reason)] for one ingredient line; [] when it passes."""
    text = PLANT.sub(" ", line)
    text = BIVALVES.sub(" ", text)
    hits: list[tuple[str, str]] = []
    for rx, why in _FLAG_RES:
        for m in rx.finditer(text):
            hits.append((m.group(0), why))
    return hits


def scan(ingredients: list[str]) -> list[tuple[int, str, str, str]]:
    """[(index, line, word, reason)] over a flat ingredient list."""
    out = []
    for i, line in enumerate(ingredients):
        for word, why in check(line):
            out.append((i, line, word, why))
    return out
