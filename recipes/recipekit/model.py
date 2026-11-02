"""The recipe JSON contract shared by the vault notes and the Console card.

A recipe is one JSON object. The Console card fields are ``title``, ``serves``,
``time`` ({prep, cook, total}), ``ingredients``, ``steps`` and ``notes`` (see
the Console's ``bridge.RECIPE_PROMPT``). This module adds one optional field,
``cfe``, which holds the Cooking for Engineers tree::

    "cfe": {
      "before": ["Preheat the oven to 350°F (175°C)"],
      "ops": [
        {"op": "mash", "in": [0]},
        {"op": "melt", "in": [1]},
        {"op": "stir", "in": ["@0", "@1", 2], "name": "wet mix"},
        {"op": "bake 55 min", "in": ["@2"], "timer": 3300}
      ]
    }

An integer input is an ingredient index: the flattened ingredient list counted
from 0, with groups flattened in order and group titles not counted. The
Console keys its ingredient checkboxes the same way. ``"@k"`` is the result of
op k. ``before`` holds setup steps that Michael Chu draws as full-width rows
above the grid. ``name`` marks a sub-recipe; the vault table outlines it and
gives it a title row. ``timer`` is seconds. The last op is the finished dish.

INVARIANTS (validate() reports a break as an error):
- Every ingredient goes into exactly one op.
- An op input is an existing ingredient or an EARLIER op, so there is no cycle.
- Every op except the last feeds exactly one later op.
- An op label is not empty, and an op has at least one input.
forest() never raises: it drops bad inputs and draws whatever is left, so a
renderer always has something to show while validate() names the problem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

REF_RE = re.compile(r"^@(\d+)$")
MAX_LABEL = 60


def flatten(ingredients: Any) -> list[str]:
    """The flat ingredient list that cfe indexes count."""
    out: list[str] = []
    for it in ingredients or []:
        if isinstance(it, dict) and isinstance(it.get("items"), list):
            out.extend(str(x) for x in it["items"])
        else:
            out.append(str(it))
    return out


def groups(ingredients: Any) -> list[tuple[str | None, list[int]]]:
    """[(group title or None, [flat indexes])], in order."""
    out: list[tuple[str | None, list[int]]] = []
    n = 0
    for it in ingredients or []:
        if isinstance(it, dict) and isinstance(it.get("items"), list):
            idx = list(range(n, n + len(it["items"])))
            n += len(it["items"])
            out.append((str(it.get("group") or "").strip() or None, idx))
        else:
            if out and out[-1][0] is None:
                out[-1][1].append(n)
            else:
                out.append((None, [n]))
            n += 1
    return out


def parse_ref(x: Any) -> tuple[str, int] | None:
    """An op input as ("ing", index) or ("op", index); None if malformed."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return ("ing", x)
    if isinstance(x, str):
        s = x.strip()
        m = REF_RE.match(s)
        if m:
            return ("op", int(m.group(1)))
        if s.isdigit():
            return ("ing", int(s))
    return None


@dataclass
class Node:
    kind: str                      # "ing" or "op"
    index: int                     # ingredient index or op index
    label: str
    children: list[Node] = field(default_factory=list)
    timer: int | None = None
    name: str | None = None

    def leaves(self) -> list[Node]:
        if self.kind == "ing":
            return [self]
        return [leaf for c in self.children for leaf in c.leaves()]

    def height(self) -> int:
        return 0 if self.kind == "ing" else 1 + max(c.height() for c in self.children)


@dataclass
class Report:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _ops(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    cfe = recipe.get("cfe") or {}
    ops = cfe.get("ops") if isinstance(cfe, dict) else None
    return [op for op in ops if isinstance(op, dict)] if isinstance(ops, list) else []


def validate(recipe: dict[str, Any]) -> Report:
    errors: list[str] = []
    warnings: list[str] = []
    ings = flatten(recipe.get("ingredients"))
    if not ings:
        errors.append("the recipe has no ingredients")
    if not recipe.get("steps"):
        warnings.append("the recipe has no method steps")
    cfe = recipe.get("cfe")
    if not cfe:
        warnings.append("no Cooking for Engineers tree yet (cfe)")
        return Report(errors, warnings)
    if not isinstance(cfe, dict):
        return Report(errors + ["cfe must be an object"], warnings)
    before = cfe.get("before") or []
    if not isinstance(before, list) or not all(isinstance(b, str) for b in before):
        errors.append("cfe.before must be a list of strings")
    raw_ops = cfe.get("ops")
    if not isinstance(raw_ops, list) or not raw_ops:
        return Report(errors + ["cfe.ops must be a non-empty list"], warnings)
    ops = raw_ops
    ing_uses = [0] * len(ings)
    op_uses = [0] * len(ops)
    for k, op in enumerate(ops):
        if not isinstance(op, dict):
            errors.append(f"op {k}: not an object")
            continue
        label = str(op.get("op") or "").strip()
        tag = f"op {k} ({label or 'no label'})"
        if not label:
            errors.append(f"{tag}: empty label")
        elif len(label) > MAX_LABEL:
            warnings.append(f"{tag}: label is over {MAX_LABEL} characters; a table cell wants a verb phrase")
        ins = op.get("in")
        if not isinstance(ins, list) or not ins:
            errors.append(f"{tag}: no inputs")
            continue
        for x in ins:
            ref = parse_ref(x)
            if ref is None:
                errors.append(f"{tag}: bad input {x!r} (use an ingredient number or '@<op number>')")
                continue
            kind, i = ref
            if kind == "ing":
                if 0 <= i < len(ings):
                    ing_uses[i] += 1
                else:
                    errors.append(f"{tag}: ingredient {i} does not exist (there are {len(ings)}, numbered from 0)")
            elif 0 <= i < k:
                op_uses[i] += 1
            else:
                errors.append(f"{tag}: @{i} is not an earlier op")
        timer = op.get("timer")
        if timer is not None and (isinstance(timer, bool) or not isinstance(timer, int) or timer <= 0):
            errors.append(f"{tag}: timer must be a whole number of seconds")
        name = op.get("name")
        if name is not None and not str(name).strip():
            errors.append(f"{tag}: empty name")
    for i, n in enumerate(ing_uses):
        if n == 0:
            errors.append(f"ingredient {i} ({ings[i]}) goes into no op")
        elif n > 1:
            errors.append(f"ingredient {i} ({ings[i]}) goes into {n} ops; give each use its own ingredient line")
    for k, n in enumerate(op_uses[:-1]):
        label = str(ops[k].get("op") or "") if isinstance(ops[k], dict) else ""
        if n == 0:
            errors.append(f"op {k} ({label}) feeds no later op; only the last op is the finished dish")
        elif n > 1:
            errors.append(f"op {k} ({label}) feeds {n} ops; the table is a tree, so split the batch into two ops")
    return Report(errors, warnings)


def forest(recipe: dict[str, Any], names: bool = True) -> list[Node]:
    """The tree(s) to draw, built tolerantly.

    A bad or forward input is dropped, an op left with no inputs is dropped, a
    reused ingredient or op shows twice, and anything that feeds nothing becomes
    its own root. The last op's tree comes first, then other loose ops, then
    loose ingredients.
    """
    ings = flatten(recipe.get("ingredients"))
    ops = _ops(recipe)
    built: list[Node | None] = []
    fed: set[int] = set()
    used: set[int] = set()
    for k, op in enumerate(ops):
        timer = op.get("timer")
        node = Node(
            "op", k, str(op.get("op") or "").strip() or "?",
            timer=timer if isinstance(timer, int) and not isinstance(timer, bool) and timer > 0 else None,
            name=(str(op.get("name")).strip() or None) if names and op.get("name") else None,
        )
        for x in op.get("in") or []:
            ref = parse_ref(x)
            if ref is None:
                continue
            kind, i = ref
            if kind == "ing" and 0 <= i < len(ings):
                node.children.append(Node("ing", i, ings[i]))
                used.add(i)
            elif kind == "op" and 0 <= i < k and built[i] is not None:
                child = built[i]
                assert child is not None
                node.children.append(child)
                fed.add(i)
        built.append(node if node.children else None)
    roots: list[Node] = []
    last = next((n for n in reversed(built) if n is not None), None)
    if last is not None:
        roots.append(last)
    roots += [n for k, n in enumerate(built) if n is not None and n is not last and k not in fed]
    roots += [Node("ing", i, ings[i]) for i in range(len(ings)) if i not in used] if ops else []
    return roots
