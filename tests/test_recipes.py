"""recipes/recipekit: the CfE tree contract, scaling, vegan screen, notes, card, nutrition.

The recipe_grid and PyYAML parts skip when those libraries are absent (the CLI
gets them from its uv script header). Run everything with:
    uv run --with pytest --with pyyaml --with recipe_grid==2.1.1 pytest tests/test_recipes.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "recipes"))

from recipekit import card, fdcdata, importer, model, note, nutrition, scale, vegan  # noqa: E402


def bread() -> dict:
    return {
        "title": "Bread",
        "ingredients": ["2 large ripe bananas (250 g)", "6 tbsp vegan butter", "1 tsp vanilla",
                        {"group": "Dry", "items": ["1 1/3 cups flour (167 g)", "1/2 tsp salt"]}, "1/2 cup walnuts"],
        "steps": ["Mash.", {"text": "Bake 55 minutes.", "timer": 3300}],
        "cfe": {"before": ["Preheat the oven to 350°F"], "ops": [
            {"op": "mash", "in": [0]}, {"op": "melt", "in": [1]},
            {"op": "stir", "in": ["@0", "@1", 2], "name": "wet mix"},
            {"op": "whisk", "in": [3, 4]},
            {"op": "fold", "in": ["@2", "@3", 5]},
            {"op": "bake 55 min", "in": ["@4"], "timer": 3300}]},
    }


# ---------- model ----------

def test_flatten_and_groups_share_one_index_space():
    r = bread()
    assert model.flatten(r["ingredients"])[3] == "1 1/3 cups flour (167 g)"
    assert model.groups(r["ingredients"]) == [(None, [0, 1, 2]), ("Dry", [3, 4]), (None, [5])]


def test_valid_tree_passes():
    rep = model.validate(bread())
    assert rep.ok, rep.errors


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r["cfe"]["ops"][3]["in"].remove(4), "ingredient 4 (1/2 tsp salt) goes into no op"),
    (lambda r: r["cfe"]["ops"][3]["in"].append(0), "goes into 2 ops"),
    (lambda r: r["cfe"]["ops"][0]["in"].append("@3"), "@3 is not an earlier op"),
    (lambda r: r["cfe"]["ops"][4]["in"].remove("@3"), "op 3 (whisk) feeds no later op"),
    (lambda r: r["cfe"]["ops"][1]["in"].append("x"), "bad input 'x'"),
    (lambda r: r["cfe"]["ops"][1].update(op=""), "empty label"),
    (lambda r: r["cfe"]["ops"][2]["in"].append(9), "ingredient 9 does not exist"),
    (lambda r: r["cfe"]["ops"][5].update(timer=1.5), "timer must be a whole number"),
])
def test_validate_names_each_break(mutate, needle):
    r = bread()
    mutate(r)
    rep = model.validate(r)
    assert not rep.ok
    assert any(needle in e for e in rep.errors), rep.errors


def test_forest_is_tolerant():
    r = bread()
    r["cfe"]["ops"][3]["in"] = [3, "@9", "junk"]       # salt left out, bad refs dropped
    roots = model.forest(r)
    assert roots[0].label == "bake 55 min"
    assert [n.label for n in roots[1:]] == ["1/2 tsp salt"]  # the loose ingredient becomes its own root
    assert [leaf.index for leaf in roots[0].leaves()] == [0, 1, 2, 3, 5]
    assert roots[0].height() == 4


def test_forest_without_cfe_is_empty():
    assert model.forest({"ingredients": ["salt"]}) == []


# ---------- scale ----------

@pytest.mark.parametrize("text, factor, want", [
    ("2 large ripe bananas (250 g)", 1.5, "3 large ripe bananas (375 g)"),
    ("1 (15 oz) can black beans", 2, "2 (15 oz) can black beans"),
    ("1 1/3 cups flour (167 g)", 1.5, "2 cups flour (250 g)"),
    ("2-3 cloves garlic", 2, "4-6 cloves garlic"),
    ("½ tsp salt", 2, "1 tsp salt"),
    ("1 9-inch pie crust", 2, "2 9-inch pie crust"),
    ("1 cup V8 juice", 3, "3 cup V8 juice"),
    ("salt to taste", 4, "salt to taste"),
    ("6 tbsp butter (85 g)", 1.5, "9 tbsp butter (128 g)"),
    ("1/3 cup sugar", 0.5, "0.17 cup sugar"),
])
def test_scale_text(text, factor, want):
    assert scale.scale_text(text, factor) == want


def test_split_quantity():
    assert scale.split_quantity("2 large ripe bananas") == ("2 large", " ripe bananas")
    assert scale.split_quantity("1 1/2 cups (360 ml) water") == ("1 1/2 cups", " (360 ml) water")
    assert scale.split_quantity("salt") == ("", "salt")


# ---------- vegan ----------

@pytest.mark.parametrize("line, flagged", [
    ("6 tbsp butter", True), ("2 tbsp peanut butter", False), ("1 tbsp oyster sauce", False),
    ("2 eggs", True), ("1 eggplant", False), ("1 tsp cream of tartar", False), ("1 tbsp honey", True),
    ("1/4 cup dandelion honey", False), ("1 tsp anchovy paste", True), ("1 can coconut milk", False),
    ("1 cup soy milk", False), ("150-200 ml soya milk", False), ("12 mussels", False), ("1 lb shrimp", True), ("2 cups vegetable broth", False),
    ("1 cup chicken broth", True), ("1/3 cup half and half", True), ("1/2 cup vegan butter", False), ("1 tbsp worcestershire sauce", True),
])
def test_vegan_screen(line, flagged):
    assert bool(vegan.check(line)) is flagged


# ---------- note ----------

def test_ingredients_md_breaks_lists_between_groups():
    md = note.ingredients_md(bread()["ingredients"])
    assert md.split("\n")[:4] == ["- 2 large ripe bananas (250 g)", "- 6 tbsp vegan butter", "- 1 tsp vanilla", ""]
    assert "**Dry**" in md
    assert md.rstrip().endswith(note.LIST_BREAK + "\n\n- 1/2 cup walnuts")


def _note_text() -> str:
    n = note.new_note(Path("/x/Bread.md"), {}, {k: v for k, v in bread().items() if k != "title"}, "A loaf.", "Ripe ones.")
    note.render(n, lambda r: "<div class=\"cfe\">T</div>")
    return note.serialize(n)


def test_render_round_trip_is_stable():
    text = _note_text()
    n = note.parse(text, Path("/x/Bread.md"))
    assert n.data["cfe"]["ops"][-1]["op"] == "bake 55 min"
    note.render(n, lambda r: "<div class=\"cfe\">T</div>")
    assert note.serialize(n) == text
    assert [s.heading for s in n.sections] == [None, "Ingredients", "Method", "Cooking for Engineers", "Notes", "Cook log"]
    assert note.notes_text(n) == "Ripe ones."


def test_hand_edit_stops_render_until_forced():
    text = _note_text().replace("- 1 tsp vanilla", "- 2 tsp vanilla")
    n = note.parse(text, Path("/x/Bread.md"))
    assert note.hand_edits(n) == ["Ingredients"]
    with pytest.raises(note.HandEdit):
        note.render(n, lambda r: "T")
    note.render(n, lambda r: "T", force=True)
    assert "- 1 tsp vanilla" in note.serialize(n)


def test_free_sections_are_kept():
    text = _note_text().replace("Ripe ones.", "Ripe ones.\n\n> [!alex] use 3 bananas")
    n = note.parse(text, Path("/x/Bread.md"))
    note.render(n, lambda r: "T2")
    out = note.serialize(n)
    assert "> [!alex] use 3 bananas" in out and "T2" in out


def test_recipe_of_builds_the_card_shape():
    n = note.parse(_note_text(), Path("/x/Bread.md"))
    n.frontmatter = {"servings": 10, "yield": "1 loaf", "prep_min": 15, "total_min": 80}
    r = note.recipe_of(n)
    assert r["serves"] == "10 (1 loaf)"
    assert r["time"] == {"prep": "15 min", "total": "1 hr 20 min"}
    assert r["cfe"]["ops"][0] == {"op": "mash", "in": [0]}


def test_frontmatter_round_trip():
    pytest.importorskip("yaml")
    import datetime as dt

    n = note.new_note(Path("/x/B.md"), {"tags": ["recipe"], "type": "recipe", "added": dt.date(2026, 11, 2),
                                         "rating": None}, {"ingredients": ["salt"], "steps": ["Salt."]})
    note.render(n, lambda r: "")
    text = note.serialize(n)
    assert text.startswith("---\ntype: recipe\nadded: 2026-11-02\ntags:\n  - recipe\n---\n")
    back = note.parse(text, Path("/x/B.md"))
    assert back.frontmatter["added"] == dt.date(2026, 11, 2)
    line = note.log_cook(back, dt.date(2026, 11, 3), 4, "Good.")
    assert line == "- 2026-11-03: 4/5 · Good."
    assert back.frontmatter["status"] == "tested" and back.frontmatter["times_cooked"] == 1
    assert note.NO_COOKS not in note.serialize(back)


# ---------- card ----------

def test_card_fence_is_compact_and_scales():
    r = {**bread(), "serves": "10 slices", "notes": "a ``` b"}
    f = card.fence(r, 2)
    body = f.split("\n")[1]
    assert f.startswith("```recipe\n") and f.endswith("\n```") and "```" not in body
    obj = json.loads(body)
    assert obj["serves"] == "20 slices"
    assert obj["ingredients"][0] == "4 large ripe bananas (500 g)"
    assert obj["steps"][1]["timer"] == 3300


# ---------- grid (recipe_grid) ----------

def test_table_html_escapes_and_adds_setup_rows():
    pytest.importorskip("recipe_grid")
    from recipekit import grid

    r = bread()
    r["ingredients"][2] = "1 tsp vanilla & <b>"
    html = grid.table_html(r)
    assert "\n" not in html and html.startswith('<div class="cfe"><table class="rg-table"><tr><td class="cfe-before"')
    assert "vanilla &amp; &lt;b&gt;" in html and "<b>" not in html
    assert '<span class="cfe-qty">2 large</span>' in html
    assert ">wet mix<" in html                      # the named op is a titled sub-recipe


def test_layout_matches_the_cfe_rules():
    pytest.importorskip("recipe_grid")
    from recipekit import grid

    t = grid.layout(bread())[0]
    assert (t["rows"], t["cols"]) == (6, 5)
    cell = {(c["r"], c["c"]): c for c in t["cells"]}
    assert cell[(0, 1)]["text"] == "mash" and cell[(0, 2)]["rs"] == 3          # stir spans its three rows
    assert cell[(2, 0)]["cs"] == 2                                             # vanilla stretches to stir
    assert cell[(3, 1)]["text"] == "whisk" and cell[(3, 1)]["cs"] == 2         # whisk stretches to fold
    assert cell[(5, 0)]["cs"] == 3 and cell[(0, 3)]["rs"] == 6                 # walnuts reach fold; fold spans all


# ---------- nutrition (no network, no parser) ----------

def amt(q, unit="", singular=False):
    return SimpleNamespace(quantity=q, unit=unit, SINGULAR=singular, RANGE=False, quantity_max=q)


FOODS = {
    1: {"description": "Bananas, raw", "foodNutrients": [{"nutrient": {"number": "208", "unitName": "kcal"}, "amount": 100},
                                                         {"nutrient": {"number": "203", "unitName": "g"}, "amount": 1}],
        "foodPortions": [{"amount": 1, "gramWeight": 120, "modifier": "medium", "measureUnit": {"name": "undetermined"}}]},
    2: {"description": "Oil, olive", "foodNutrients": [{"nutrient": {"number": "204", "unitName": "g"}, "amount": 100}],
        "foodPortions": [{"amount": 1, "gramWeight": 216, "modifier": "cup", "measureUnit": {"name": "undetermined"}}]},
    3: {"description": "Baobab powder", "foodNutrients": [], "foodPortions": []},
}
LINES = {
    "2 bananas": ([amt(2)], 1, "Bananas, raw", "bananas"),
    "2 tbsp olive oil": ([amt(2, "tablespoon")], 2, "Oil, olive", "olive oil"),
    "100 g bananas": ([amt(100, "gram")], 1, "Bananas, raw", "bananas"),
    "1 tsp baking powder": ([amt(1, "teaspoon")], 3, "Baobab powder", "baking powder"),
    "1 cup soy curls": ([amt(1, "cup")], None, "", "soy curls"),
    "water": ([], None, "", "water"),
}


def test_nutrition_compute_paths():
    res = nutrition.compute(list(LINES), {"5": {"skip": True}, "4": {"kcal": 300, "protein": 30}}, servings=2,
                            parse_line=lambda s: LINES[s], food_of=lambda i, description="": FOODS[i])
    rows = {r["line"]: r for r in res["rows"]}
    assert rows["2 bananas"]["grams"] == 240 and rows["2 bananas"]["kcal"] == pytest.approx(240)
    oil = rows["2 tbsp olive oil"]
    assert oil["grams"] == pytest.approx(2 * 14.7868 * 216 / 236.588) and "Atwater" in oil["flags"]
    assert rows["100 g bananas"]["kcal"] == pytest.approx(100)
    assert "check match" in rows["1 tsp baking powder"]["flags"]
    assert rows["1 cup soy curls"]["kcal"] == 300 and rows["water"]["flags"] == ["skipped"]
    assert res["per_serving"]["kcal"] == pytest.approx((240 + oil["kcal"] + 100 + 300) / 2)
    assert res["open"] == 1
    md = nutrition.markdown(res)
    assert md.startswith("Per serving (2 servings): **") and "| 0 | 2 bananas |" in md


def test_item_grams_prefers_the_whole_fruit():
    lemon = {"foodPortions": [{"modifier": "62000", "portionDescription": "1 slice or wedge", "gramWeight": 8},
                              {"modifier": "90000", "portionDescription": "Quantity not specified", "gramWeight": 15},
                              {"modifier": "10205", "portionDescription": "1 cup", "gramWeight": 200},
                              {"modifier": "60813", "portionDescription": "1 fruit", "gramWeight": 65}]}
    assert nutrition.item_grams(lemon, "1/2 lemon") == (65, True)
    assert nutrition.density(lemon) == pytest.approx(200 / 236.588)


def test_suspicious_match():
    assert nutrition.suspicious("baking powder", "Baobab powder")
    assert not nutrition.suspicious("ripe bananas", "Bananas, ripe and slightly ripe, raw")
    assert not nutrition.suspicious("all-purpose flour", "Flour, wheat, all-purpose, unenriched, unbleached")


# ---------- fdcdata, importer ----------

def test_iter_foods_streams_across_chunk_edges_and_skips_nothing():
    foods = [{"fdcId": i, "description": f"food {i}", "pad": "x" * (i * 7)} for i in range(40)]
    text = json.dumps({"FoundationFoods": foods[:20] + [None] + foods[20:]})
    got = list(fdcdata.iter_foods(io.StringIO(text), chunk=64))
    assert [f["fdcId"] for f in got if isinstance(f, dict)] == list(range(40))
    assert got.count(None) == 1


def test_regroup_repairs_a_bad_fuzzy_match():
    flat = ["1/2 cup almond butter", "1 tsp lime zest", "1/2 cup cashews (soaked)", "1/3 cup coconut cream", "1 tbsp coconut oil"]
    bad = [("For the Base", flat[:2]), ("Topping", ["1/2 cup cashews (soaked)", "1/2 cup cashews (soaked)", "1 tbsp coconut oil"])]
    assert importer.regroup(bad, flat) == [{"group": "For the Base", "items": flat[:2]}, {"group": "Topping", "items": flat[2:]}]
    good = [("Base", flat[:2]), ("Topping", flat[2:])]
    assert importer.regroup(good, flat)[1] == {"group": "Topping", "items": flat[2:]}
    assert importer.regroup([("Base", flat[:2])], flat) == flat                   # one group: flat
    assert importer.regroup([("A", flat[:1]), ("B", flat[1:2])], flat) == flat     # sizes do not add up


def test_ld_ingredient_count_reads_graph():
    page = ('<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},'
            '{"@type":["Recipe"],"name":"X","recipeIngredient":["a","b","c"]}]}</script>')
    assert importer.ld_ingredient_count(page) == 3
    assert importer.ld_ingredient_count("<html></html>") is None
