"""The Console's ```recipe fence, built from a note (or a recipe object).

MIST prints this with `recipe card <name>` and pastes it into a reply; the
Console draws it as the recipe card, and the ``cfe`` field turns on its
Cooking for Engineers toggle. Building the fence here means the reply never
retypes a recipe by hand.

INVARIANTS:
- The fence is compact one-line JSON with no ``` inside it (the Console's
  markdown pass ends a fence at the first ```).
- Scaling changes ingredient quantities and the serves line only; step text
  keeps its times and temperatures.
"""

from __future__ import annotations

import json
from typing import Any

from .scale import scale_serves, scale_text


def scaled(recipe: dict[str, Any], factor: float) -> dict[str, Any]:
    if factor == 1:
        return recipe
    out = dict(recipe)
    ings: list[Any] = []
    for it in recipe.get("ingredients") or []:
        if isinstance(it, dict) and isinstance(it.get("items"), list):
            ings.append({**it, "items": [scale_text(str(x), factor) for x in it["items"]]})
        else:
            ings.append(scale_text(str(it), factor))
    out["ingredients"] = ings
    if recipe.get("serves"):
        out["serves"] = scale_serves(str(recipe["serves"]), factor)
    note = f"Scaled ×{factor:g}; times in the steps are for the original size."
    out["notes"] = (str(recipe.get("notes") or "") + " " + note).strip()
    return out


def fence(recipe: dict[str, Any], factor: float = 1.0) -> str:
    obj = {k: v for k, v in scaled(recipe, factor).items() if v not in (None, "", [], {})}
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("```", "``​`")
    return "```recipe\n" + text + "\n```"
