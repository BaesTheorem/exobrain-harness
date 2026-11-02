# Recipes design

Two surfaces show a recipe. Each one has its own locked look.

## Obsidian: direction 3, "branch blocks"

Picked 2026-11-02. The Cooking for Engineers table in a recipe note draws a
thick outline around each named sub-recipe (the wet mix, the dry mix), with a
title row, so the branches of the recipe read as blocks. Reference:
[recipe_grid](https://mossblaser.github.io/recipe_grid/), whose layout engine
draws the grid.

The style lives in `<vault>/.obsidian/snippets/recipes.css`. The HTML gets
classes only (no inline style), so a style change never needs a re-render.

- **Fonts:** the theme's text face (system sans) for ingredients and
  operations. SF Mono for quantities and sub-recipe titles.
- **Palette** (five tokens):

  | Token | Dark | Light | Use |
  | --- | --- | --- | --- |
  | `--cfe-ink` | `var(--text-normal)` | same | cell text |
  | `--cfe-muted` | `var(--text-muted)` | same | setup rows ("Preheat the oven") |
  | `--cfe-line` | `var(--background-modifier-border)` | same | the 1px grid |
  | `--cfe-block` | `#dcbce1` | `#6f5675` | the 2px sub-recipe outline |
  | `--cfe-block-fill` | `#563e5c` | `#f9d8fe` | the sub-recipe title row |

  The two block colors are MD3 tertiary and tertiary container from the
  theme accent `#4d94f7` (material-color-utilities, tonal spot scheme).
- **Spacing:** 8px scale. Table cells use a 4px half-step vertically
  (`4px 8px`), and the table sits 16px from the text around it.
- **Radius:** 0.
- No gradients or shadows unless listed here.

## MIST Console: the Console design

The table view inside the Console recipe card adds no new tokens. It uses the
recipe card's own language (`mist-console/static/style.css`, "recipe cards"):
hairline borders in `--line`, `--teal` for structure and operation text,
`--gold` for a running timer and `--err` for a finished one, the Console body
face (SF Mono), and square corners. Ingredient checkboxes are the same
elements as in the list view and share their state. An operation with a timer
or a duration gets its own timer chip, separate from the step timers.
