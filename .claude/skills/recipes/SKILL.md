---
name: recipes
description: Alex's recipe manager. Each recipe is a note in the vault's Recipes/ folder, listed by Recipes.base, with the traditional format (ingredients and method) and a Cooking for Engineers table built from one data block. Use when Alex says "/recipes", "add this recipe", "save this recipe", "import this recipe" (a URL, a photo, pasted text, an Apple Note), "convert this to Cooking for Engineers", "make the table for", "show me the recipe for", "what can I cook", "something quick for dinner", "high-protein dinner", "what haven't I made lately", "I made X", "log that I cooked", "rate the recipe", "scale this to N servings", "double it", "how many calories in", "macros for this recipe", "is this vegan", "veganize this", or edits a recipe note by hand.
---

# Recipes

Every recipe is one note in `~/Exobrain/Recipes/`. `~/Exobrain/Recipes.base` shows them (gallery, all, to try, quick, high protein, not cooked lately). The tool is `recipes/bin/recipe` in the harness (run it with its path; uv brings recipe_grid, ingredient-parser, recipe-scrapers and PyYAML).

The JSON data block at the bottom of a note (the collapsed "Recipe data" callout) is the source. `recipe render` builds the Ingredients, Method and Cooking for Engineers sections from it. Never type into those three sections or the data block by hand: change the data with `recipe put`, or take Alex's edits in with `recipe adopt`. The frontmatter (course, cuisine, status, rating, times, servings, image, key_ingredients) is free to edit with `obsidian property:set` or `recipe put` (`"meta"`).

## Commands

| Task | Command |
| --- | --- |
| New recipe from a JSON file | `recipe new --file r.json [--set course=main]` |
| Import from a URL | `recipe import URL` (reads the page's schema.org JSON-LD and compares the ingredient count with it) |
| Read one | `recipe show NAME --json` |
| Change ingredients, steps, cfe, nutrition overrides | `recipe put NAME --file r.json` |
| Take Alex's hand edits in Ingredients/Method into the data | `recipe adopt NAME` |
| Rebuild the generated sections | `recipe render NAME` or `--all` |
| Problems: tree errors, vegan flags, hand edits, stale nutrition | `recipe check NAME` or `--all` |
| Show it in the Console | `recipe card NAME [--scale 2]`, then paste the fence |
| Log a cook | `recipe cooked NAME --rating 4 --note "less sugar"` |
| kcal and protein per serving | `recipe nutrition NAME` |
| Search | `recipe find --max-min 30 --course main --has tofu --sort protein` |

A recipe JSON file is the Console card shape plus `cfe`, `meta` and `description`:

```json
{"title": "...", "serves": "4", "time": {"prep": "10 min", "cook": "20 min", "total": "30 min"},
 "ingredients": ["...", {"group": "Sauce", "items": ["..."]}], "steps": ["...", {"text": "...", "timer": 600}],
 "notes": "...", "cfe": {"before": ["..."], "ops": [{"op": "...", "in": [0, "@1"]}]},
 "meta": {"course": "main", "cuisine": "Thai", "key_ingredients": ["tofu"], "source": "https://..."}}
```

## Show a recipe in chat

Run `recipe card NAME` and paste its output as the reply's card. Never retype a recipe that is in the vault. The Console draws the card with a list/table toggle when `cfe` is present. For a recipe that is not in the vault, write the fence by hand, `cfe` included (the Console's system prompt has the contract).

## Convert a recipe to Cooking for Engineers

This is the one step that needs judgment, and `recipes/bench/` grades it against Michael Chu's own tables. Read the whole method first, then write `cfe.ops` in cooking order.

1. **One op per action on a set of inputs.** An op is a short verb phrase, as in Chu's tables: "mash", "melt", "whisk", "cream", "fold", "simmer 10 min", "bake 350°F 55 min", "cool on a wire rack". Put the temperature and the time in the label when the step has them.
2. **An op combines its inputs at the moment the method brings them together.** If the method whisks the flour, soda and salt, then folds them into the wet mix with the nuts, write `whisk [flour, soda, salt]`, then `fold [@wet, @whisk, nuts]`.
3. **Every ingredient goes in exactly once.** If the method uses an ingredient in two places ("half the sugar now, half later"), split it into two ingredient lines first ("1/4 cup sugar (for the topping)").
4. **Every op except the last feeds exactly one later op.** Sequential actions on one thing are a chain: `bake` then `cool 10 min in pan` then `cool on a wire rack`. The last op is the finished dish.
5. **Preparation is an op, not ingredient text.** "1 onion, diced" becomes the line "1 onion" and the op `dice [onion]`; the method keeps saying "Dice the onion."
6. **Setup that uses no ingredient goes in `before`**: preheat the oven, oil the pan, bring a pot of water to a boil when the water is not an ingredient line.
7. **Order inputs top to bottom in the order the cook touches them**, so the table reads like the method. Put a single-ingredient prep (mash, melt) before the ingredients it later joins.
8. **Name a branch** (`"name"`) when it is a component a cook would call by name: dough, sauce, filling, glaze, wet mix, dry mix. One to three per recipe. The vault table outlines named branches.
9. **Timers** (`"timer"`, seconds) go on ops that wait: bake, simmer, rest, chill, proof, marinate.
10. Garnish and serve-with items join the last op ("serve with lime wedges").

Then run `recipe put NAME --file r.json`. It refuses a tree that breaks a rule and says which one.

## Add a recipe

- **URL:** `recipe import URL`. Check the ingredient count line it prints (the page's JSON-LD is the reference). Then write the `cfe` tree and `recipe put`.
- **Pasted text, a photo, a Supernote page, an Apple Note:** transcribe into a recipe JSON (keep the author's quantities and wording, add grams where the source gives them), write the tree, `recipe new`. Put the source in `meta.source` (a URL, or `"[[Archive/Apple Notes/...]]"`).
- Set `meta.course` (main, side, breakfast, dessert, drink, sauce, snack, bread, soup, salad), `meta.cuisine`, `meta.key_ingredients` (two to four foods Alex would search for), and `meta.image` when the source has a photo URL.
- Then `recipe nutrition NAME` (see below) and `recipe check NAME`.

## Vegan

The screen is bivalve-inclusive: oysters, mussels, clams and scallops pass, so oyster sauce passes (the diet rules are in MIST's memory, `user_vegan`). `recipe check` flags animal products by keyword. For each flag, propose a swap that works in the dish (vegan butter, aquafaba or flax egg by the egg's job, soy or oat milk, miso or seaweed for fish sauce). Swap only with Alex's yes, then `recipe put`. The screen cannot see hidden animal products in branded items (some sugars, wines, "natural flavors"); say so when it matters.

## Nutrition

`recipe nutrition NAME` writes kcal and protein per serving to the frontmatter and a per-ingredient table to the note. It uses ingredient-parser's USDA FoodData Central matches and a local USDA index (`recipe fdc-update` builds it once; no API key). Read the Check column:

- **check match**: a word of the ingredient is missing from the USDA description (baking powder matched to baobab powder). Find the right food and add an override.
- **no match**: branded or unusual items (soy curls, vegan butter). Use the package label.
- **est.**: the weight comes from a guess (no portion data). A gram weight in the ingredient line fixes it.

Overrides go in the data block's `nutrition` map, keyed by ingredient index: `{"3": {"kcal": 100, "protein": 10}}` (label values for the whole line), `{"4": {"fdc_id": 173430}}`, `{"5": {"grams": 120}}`, or `{"6": {"skip": true}}`. Get the data with `recipe show NAME --json`, add the map, `recipe put`, and run `recipe nutrition` again. The High protein view sorts by protein per 100 kcal.

## Cook log and rotation

When Alex says he made something: `recipe cooked NAME --rating N --note "what he changed"`. That sets `last_cooked`, `times_cooked`, `rating`, and moves `to-try` to `tested`. Set `status: favorite` only on his word. "What haven't I made lately" is the "Not cooked lately" view, or `recipe find --sort cooked`.

## Hand edits

Alex edits notes in Obsidian. `recipe check` names a generated section that changed since the last render. If it is Ingredients or Method, run `recipe adopt NAME`, which reads his text back into the data and re-renders. If the ingredient count changed, the tree's numbers are off: fix `cfe` and `recipe put`. Never use `render --force` over his text without his yes. His `> [!alex]` callouts and the Notes section are his and stay untouched.

## Scale

`recipe card NAME --scale 1.5` scales quantities in the card only (sizes like "(15 oz) can" and temperatures stay). Times in the steps do not scale, and the card says so. To change the saved recipe, write the scaled lines with `recipe put`.
