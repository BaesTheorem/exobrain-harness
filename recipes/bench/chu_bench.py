#!/usr/bin/env python3
"""Held-out test of the Cooking for Engineers conversion against Michael Chu's own tables.

The conversion (prose method -> cfe tree) is the one step of the recipe
manager that needs judgment, so it gets a judge that is neither MIST nor Alex:
the tables Michael Chu drew by hand on cookingforengineers.com.

    chu_bench.py prepare [-n 12]     fetch pages, write inputs/ (title, ingredients
                                      in alphabetical order, the prose method) and
                                      gold/ (the tree read back from Chu's table)
    chu_bench.py score               compare pred/<id>.json (a cfe object, written by
                                      a converter that saw only inputs/) with gold/

Everything lands in recipes/bench/.cache/ (gitignored: the pages are Chu's
copyrighted work, so only code and scores go in the repo).

Scoring: every op that combines two or more ingredients defines a merge group
(the set of ingredients under it). Precision and recall compare the predicted
groups with Chu's, so labels and wording never matter, only the structure.
"Prep" is the share of ingredients Chu preps on their own (mash, melt) that the
prediction also preps on their own.

INVARIANTS:
- The converter input never contains the table, and its ingredient order is
  alphabetical, because Chu's row order alone gives away the grouping.
- A page whose table does not read back as one tree with every ingredient used
  once is skipped, never scored.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recipekit import model  # noqa: E402

CACHE = Path(__file__).resolve().parent / ".cache"
SITE = "https://www.cookingforengineers.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def get(url: str) -> str:
    path = CACHE / "pages" / (re.sub(r"[^A-Za-z0-9]+", "_", url.split("//", 1)[1]) + ".html")
    if path.exists():
        return path.read_text(encoding="latin-1")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed site
        text = resp.read().decode("latin-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")
    time.sleep(1.0)
    return text


# ---------- reading a table back into a tree ----------

def _cells(table: str) -> list[list[dict]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S | re.I):
        row = []
        for attrs, body in re.findall(r"<td([^>]*)>(.*?)</td>", tr, re.S | re.I):
            rs = re.search(r'rowspan="?(\d+)', attrs, re.I)
            cs = re.search(r'colspan="?(\d+)', attrs, re.I)
            text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
            row.append({"text": text, "rs": int(rs.group(1)) if rs else 1, "cs": int(cs.group(1)) if cs else 1})
        rows.append(row)
    return rows


def _place(rows: list[list[dict]]) -> tuple[list[dict], int, int]:
    taken: dict[tuple[int, int], dict] = {}
    placed = []
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in taken:
                c += 1
            cell = {**cell, "r": r, "c": c, "id": len(placed)}
            for dr in range(cell["rs"]):
                for dc in range(cell["cs"]):
                    taken[(r + dr, c + dc)] = cell
            placed.append(cell)
            c += cell["cs"]
    ncols = max((c for _, c in taken), default=-1) + 1
    nrows = max((r for r, _ in taken), default=-1) + 1
    for cell in placed:
        cell["taken"] = taken
    return placed, nrows, ncols


def read_table(table: str) -> dict | None:
    """{"before", "ingredients", "ops": [{"label", "leaves"}]} or None if it is not one clean tree."""
    placed, nrows, ncols = _place(_cells(table))
    if ncols < 2:
        return None
    taken = placed[0]["taken"] if placed else {}
    before, first = [], 0
    for r in range(nrows):
        cell = taken.get((r, 0))
        if cell and cell["c"] == 0 and cell["cs"] == ncols and cell["rs"] == 1:
            before.append(cell["text"])
            first = r + 1
        else:
            break
    ing_cells = [cell for cell in placed if cell["c"] == 0 and cell["r"] >= first and cell["cs"] < ncols]
    ing_cells.sort(key=lambda x: x["r"])
    leaf_of = {cell["id"]: i for i, cell in enumerate(ing_cells)}

    def left_inputs(cell: dict) -> list[dict]:
        seen, out = set(), []
        for r in range(cell["r"], cell["r"] + cell["rs"]):
            left = taken.get((r, cell["c"] - 1))
            if left is not None and left["id"] not in seen:
                seen.add(left["id"])
                out.append(left)
        return out

    memo: dict[int, frozenset[int]] = {}

    def leaves(cell: dict) -> frozenset[int]:
        if cell["id"] in leaf_of:
            return frozenset([leaf_of[cell["id"]]])
        if cell["id"] not in memo:
            memo[cell["id"]] = frozenset().union(*[leaves(x) for x in left_inputs(cell)]) if cell["c"] > 0 else frozenset()
        return memo[cell["id"]]

    ops = [cell for cell in placed if cell["c"] > 0 and cell["r"] >= first and cell["text"]]
    if not ops or not ing_cells:
        return None
    out_ops = [{"label": op["text"], "leaves": sorted(leaves(op))} for op in sorted(ops, key=lambda x: (x["c"], x["r"]))]
    roots = [op for op in ops if op["c"] + op["cs"] == ncols]
    if len(roots) < 1 or set().union(*[leaves(r) for r in roots]) != set(range(len(ing_cells))):
        return None
    return {"before": before, "ingredients": [c["text"] for c in ing_cells], "ops": out_ops}


def recipe_table(page: str) -> str | None:
    best = None
    for t in re.findall(r"<table[^>]*>.*?</table>", page, re.S | re.I):
        if re.search(r"rowspan", t, re.I) and re.search(r"\d", t) and "<table" not in t[6:]:
            if best is None or len(t) > len(best):
                best = t
    return best


def prose(page: str, title: str, table: str) -> str:
    text = page.replace(table, "\n[[RECIPE TABLE]]\n")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<table.*?</table>", "\n", text, flags=re.S | re.I)
    lines = [ln.strip() for ln in html.unescape(re.sub(r"<[^>]+>", "\n", text)).split("\n") if ln.strip()]
    try:
        start = lines.index("« Prev") + 1
    except ValueError:
        start = 0
    end = lines.index("[[RECIPE TABLE]]") if "[[RECIPE TABLE]]" in lines else len(lines)
    while end > start and lines[end - 1] != title:
        end -= 1
    body = lines[start:end - 1] if end > start else lines[start:]
    out, skip = [], False
    for ln in body:
        if ln == "Related Articles":
            skip = True
            continue
        if skip and len(ln) < 60:
            continue
        skip = False
        out.append(ln)
    return "\n\n".join(out)


def cmd_prepare(n: int) -> int:
    home = get(SITE + "/")
    links = list(dict.fromkeys(re.findall(r'href="(/recipe/\d+/[^"]+)"', home)))
    more = get(SITE + "/recipes/") if len(links) < 3 * n else ""
    links += [x for x in dict.fromkeys(re.findall(r'href="(/recipe/\d+/[^"]+)"', more)) if x not in links]
    (CACHE / "inputs").mkdir(parents=True, exist_ok=True)
    (CACHE / "gold").mkdir(parents=True, exist_ok=True)
    done = 0
    for link in links:
        if done >= n:
            break
        page = get(SITE + link)
        table = recipe_table(page)
        title_m = re.search(r"<title>(.*?) - Recipe File", page, re.S)
        if not table or not title_m:
            continue
        title = html.unescape(title_m.group(1)).strip()
        gold = read_table(table)
        if gold is None or len(gold["ingredients"]) < 3:
            print(f"skip {link}: table does not read back as one tree")
            continue
        method = prose(page, title, table)
        if len(method) < 400:
            print(f"skip {link}: no prose method")
            continue
        rid = link.split("/")[2]
        names: list[str] = gold["ingredients"]
        order = sorted(range(len(names)), key=lambda i: names[i].lower())
        inputs = {"id": rid, "title": title, "ingredients": [names[i] for i in order], "method": method}
        gold["alpha_to_table"] = order
        (CACHE / "inputs" / f"{rid}.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=1))
        (CACHE / "gold" / f"{rid}.json").write_text(json.dumps({"url": SITE + link, **gold}, ensure_ascii=False, indent=1))
        done += 1
        print(f"ready {rid}: {title} ({len(gold['ingredients'])} ingredients, {len(gold['ops'])} ops)")
    return 0


def groups_of(ops_leaves: list[list[int]]) -> set[frozenset[int]]:
    return {frozenset(x) for x in ops_leaves if len(x) >= 2}


def single_prepped(ops_leaves: list[list[int]]) -> set[int]:
    return {x[0] for x in ops_leaves if len(x) == 1}


def cmd_score() -> int:
    rows = []
    for gpath in sorted((CACHE / "gold").glob("*.json")):
        gold = json.loads(gpath.read_text())
        ppath = CACHE / "pred" / gpath.name
        if not ppath.exists():
            print(f"{gpath.stem}: no prediction")
            continue
        pred = json.loads(ppath.read_text())
        alpha = gold["alpha_to_table"]
        recipe = {"ingredients": [gold["ingredients"][i] for i in alpha], "cfe": pred.get("cfe", pred)}
        rep = model.validate(recipe)
        pleaves = []
        for root in model.forest(recipe):
            stack = [root]
            while stack:
                node = stack.pop()
                if node.kind == "op":
                    pleaves.append(sorted(alpha[leaf.index] for leaf in node.leaves()))
                    stack.extend(node.children)
        g, p = groups_of([o["leaves"] for o in gold["ops"]]), groups_of(pleaves)
        hit = len(g & p)
        prec = hit / len(p) if p else 0.0
        rec = hit / len(g) if g else 1.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        gp, pp = single_prepped([o["leaves"] for o in gold["ops"]]), single_prepped(pleaves)
        prep = len(gp & pp) / len(gp) if gp else 1.0
        rows.append({"id": gpath.stem, "title": json.loads((CACHE / "inputs" / gpath.name).read_text())["title"],
                     "gold_groups": len(g), "pred_groups": len(p), "precision": prec, "recall": rec, "f1": f1,
                     "exact": g == p, "prep": prep, "valid": rep.ok})
    if not rows:
        print("nothing to score")
        return 1
    for r in rows:
        print(f"{r['id']:>4} {r['title'][:34]:<34} groups {r['pred_groups']:>2}/{r['gold_groups']:<2} "
              f"P {r['precision']:.2f} R {r['recall']:.2f} F1 {r['f1']:.2f} prep {r['prep']:.2f}"
              f"{'  exact' if r['exact'] else ''}{'' if r['valid'] else '  (invalid tree)'}")
    n = len(rows)
    print(f"\n{n} recipes: mean F1 {sum(r['f1'] for r in rows) / n:.2f}, mean precision "
          f"{sum(r['precision'] for r in rows) / n:.2f}, mean recall {sum(r['recall'] for r in rows) / n:.2f}, "
          f"exact structure {sum(r['exact'] for r in rows)}/{n}, prep {sum(r['prep'] for r in rows) / n:.2f}, "
          f"valid trees {sum(r['valid'] for r in rows)}/{n}")
    (CACHE / "score.json").write_text(json.dumps(rows, indent=1))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("-n", type=int, default=12)
    sub.add_parser("score")
    a = p.parse_args()
    return cmd_prepare(a.n) if a.cmd == "prepare" else cmd_score()


if __name__ == "__main__":
    sys.exit(main())
