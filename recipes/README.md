# recipes

A recipe manager in Obsidian. Each recipe is one note in the vault's
`Recipes/` folder, and `Recipes.base` lists them. A note shows each recipe two
ways: the traditional ingredient list and method, and a Cooking for Engineers
table, which is Michael Chu's format with ingredients down the left and each
operation in the column after its inputs. The `/recipes` skill
(`.claude/skills/recipes/SKILL.md`) is how MIST uses it. The MIST Console
recipe card has a list/table toggle for the same data.

## How a note works

The JSON data block at the bottom of a note (a collapsed "Recipe data"
callout) is the source. `recipe render` builds the Ingredients, Method and
Cooking for Engineers sections from it, and records a hash of each one. If a
section changes by hand, the next render stops and names it. `recipe adopt`
then reads the edited Ingredients or Method back into the data. The Notes and
Cook log sections, the frontmatter, and any `> [!alex]` callout are never
rewritten.

The tree contract is in `recipekit/model.py`:

```json
"cfe": {"before": ["Preheat the oven to 350°F"],
        "ops": [{"op": "mash", "in": [0]}, {"op": "fold", "in": ["@0", 1, 2], "name": "batter"},
                {"op": "bake 55 min", "in": ["@1"], "timer": 3300}]}
```

An integer input is an ingredient index (the flattened list, from 0). `"@k"`
is the result of op k. Every ingredient goes into exactly one op, every op
except the last feeds exactly one later op, and `recipe check` names any break.

## Commands

`bin/recipe` runs through uv, which brings its dependencies. `recipe --help`
has the full list:

- `recipe import URL` creates a note from a recipe page. It compares the
  ingredient count with the page's schema.org JSON-LD.
- `recipe new --file r.json` and `recipe put NAME --file r.json` create a
  note or change its data.
- `recipe render`, `recipe check`, `recipe adopt` keep notes and data in step.
- `recipe card NAME [--scale X]` prints the Console's recipe fence.
- `recipe cooked NAME --rating N --note TEXT` writes the cook log.
- `recipe nutrition NAME` writes kcal and protein per serving.
- `recipe find` searches by time, course, ingredient and status.

## Parts

| File | Job |
| --- | --- |
| `recipekit/model.py` | the recipe JSON contract, validation, the tree |
| `recipekit/grid.py` | the Cooking for Engineers HTML table, laid out by recipe_grid |
| `recipekit/note.py` | note sections, hashes, the data block, the cook log |
| `recipekit/card.py` | the Console fence |
| `recipekit/scale.py` | scaling ingredient lines (a "(15 oz) can" stays 15 oz) |
| `recipekit/vegan.py` | animal-product screen, bivalve-inclusive |
| `recipekit/nutrition.py`, `recipekit/fdcdata.py` | USDA FoodData Central nutrition from a local index of the bulk files |
| `recipekit/importer.py` | schema.org JSON-LD import (recipe-scrapers), with a WP Recipe Maker fallback |
| `bench/chu_bench.py` | the held-out test against Michael Chu's tables |
| `DESIGN.md` | the locked look of the table in Obsidian and in the Console |

The Obsidian style is `<vault>/.obsidian/snippets/recipes.css` (see
`DESIGN.md`).

## Dependencies

- [recipe_grid](https://github.com/mossblaser/recipe_grid) 2.1.1 by Jonathan
  Heathcote lays out the tables. It is GPL-3.0. uv installs it at run time, and
  none of its code is in this repo.
- [recipe-scrapers](https://github.com/hhursev/recipe-scrapers) (MIT) reads
  recipe pages.
- [ingredient-parser](https://github.com/strangetom/ingredient-parser) (MIT)
  splits ingredient lines and matches them to USDA foods.
- USDA FoodData Central bulk files (public domain). `recipe fdc-update`
  downloads every Foundation release plus SR Legacy and FNDDS (about 22 MB)
  into `~/Library/Caches/exobrain-recipes/`. No API key is necessary.

## Tests

`tests/test_recipes.py` covers the contract, scaling, the vegan screen, note
round trips, the card, nutrition math, and the streaming JSON reader. The
recipe_grid and PyYAML tests skip unless those libraries are present:

```bash
uv run --with pytest --with pyyaml --with recipe_grid==2.1.1 pytest tests/test_recipes.py
```

The Console repo's `tests/test_cfe_layout.py` checks the Console's table layout
against `recipe layout` cell for cell.

## The held-out test

The conversion from a written method to a tree is the one step that needs
judgment. `bench/chu_bench.py prepare` reads 12 recipe pages from
cookingforengineers.com. It writes the converter's input (the prose method,
with the ingredient list in alphabetical order) and, separately, the tree read
back from Chu's own table. A converter that sees only the inputs writes its
trees, and `chu_bench.py score` compares the ingredient groupings. The fetched
pages stay in the gitignored `bench/.cache/`.
