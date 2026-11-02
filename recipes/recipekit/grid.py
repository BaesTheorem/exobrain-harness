"""Cooking for Engineers tables through recipe_grid's layout engine.

recipe_grid (Jonathan Heathcote, GPL-3.0, pinned 2.1.1) lays out the grid:
ingredients down the left, each operation in the column after its inputs,
spanning the rows it combines, and a short branch stretched (colspan) to reach
the column where it joins. This module turns a model.forest() into recipe_grid
objects, renders its HTML, and adds two things recipe_grid does not draw:
Michael Chu's full-width setup rows ("Preheat the oven") above the grid, and a
span around each leading quantity so the stylesheet can set it in mono.

The output is one line of HTML inside <div class="cfe">. One line on purpose:
a blank line ends an HTML block in Obsidian, and an indented line after one
turns into a code block.

INVARIANTS:
- Every text that reaches the HTML is escaped (recipe_grid escapes its cells;
  the setup rows are escaped here).
- layout() and the Console's app.js cfeLayout() give the same cells for a tree
  without names (tests/test_cfe_layout.py in the Console repo checks it).
"""

from __future__ import annotations

import html
import re
from typing import Any

from recipe_grid.recipe import Ingredient, RecipeTreeNode, Step, SubRecipe
from recipe_grid.renderer.html import render_recipe_tree
from recipe_grid.renderer.recipe_to_table import recipe_tree_to_table
from recipe_grid.renderer.table import Cell
from recipe_grid.scaled_value_string import ScaledValueString as SVS

from . import model
from .scale import split_quantity

_TD_ING = re.compile(r'(<td class="rg-ingredient[^"]*"[^>]*>)([^<]*)(</td>)')


def to_rg(node: model.Node, index: dict[int, model.Node] | None = None, root: bool = True) -> RecipeTreeNode:
    """One model.Node tree as recipe_grid objects; index maps id(rg) -> Node."""
    if node.kind == "ing":
        rg: RecipeTreeNode = Ingredient(SVS(node.label))
    else:
        step = Step(SVS(node.label), tuple(to_rg(c, index, False) for c in node.children))
        if index is not None:
            index[id(step)] = node
        rg = SubRecipe(step, (SVS(node.name),), show_output_names=True) if node.name and not root else step
    if index is not None:
        index[id(rg)] = node
    return rg


def _wrap_quantity(m: re.Match[str]) -> str:
    text = html.unescape(m.group(2))
    lead = len(text) - len(text.lstrip())
    qty, rest = split_quantity(text[lead:])
    if not qty:
        return m.group(0)
    return (m.group(1) + html.escape(text[:lead]) + '<span class="cfe-qty">' + html.escape(qty.rstrip())
            + "</span>" + html.escape(qty[len(qty.rstrip()):] + rest) + m.group(3))


def table_html(recipe: dict[str, Any], id_prefix: str = "cfe-") -> str:
    """The Cooking for Engineers table as one line of HTML; "" if there is no tree."""
    roots = model.forest(recipe)
    if not roots:
        return ""
    cfe = recipe.get("cfe") if isinstance(recipe.get("cfe"), dict) else {}
    before = [b for b in (cfe or {}).get("before") or [] if isinstance(b, str) and b.strip()]
    parts = []
    for n, root in enumerate(roots):
        tree = to_rg(root)
        out = render_recipe_tree(tree, id_prefix=f"{id_prefix}{n}-")
        if n == 0 and before:
            cols = recipe_tree_to_table(tree).columns
            rows = "".join(
                f'<tr><td class="cfe-before" colspan="{cols}">{html.escape(b.strip())}</td></tr>' for b in before
            )
            out = out.replace('<table class="rg-table">', '<table class="rg-table">' + rows, 1)
        parts.append(out)
    one_line = re.sub(r">\s+<", "><", '<div class="cfe">' + "".join(parts) + "</div>").strip()
    one_line = re.sub(r"\s*\n\s*", " ", one_line)
    return _TD_ING.sub(_wrap_quantity, one_line)


def layout(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """recipe_grid's grid for each root, as plain data (names off, as the Console draws it).

    [{"rows": R, "cols": C, "cells": [{"r", "c", "rs", "cs", "kind", "index", "text"}]}]
    """
    tables = []
    for root in model.forest(recipe, names=False):
        index: dict[int, model.Node] = {}
        t = recipe_tree_to_table(to_rg(root, index))
        cells = []
        for r in range(t.rows):
            for c in range(t.columns):
                cell = t[r, c]
                if not isinstance(cell, Cell):
                    continue
                node = index[id(cell.value)]
                cells.append({"r": r, "c": c, "rs": cell.rows, "cs": cell.columns,
                              "kind": node.kind, "index": node.index, "text": node.label})
        tables.append({"rows": t.rows, "cols": t.columns, "cells": cells})
    return tables
