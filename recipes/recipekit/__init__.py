"""recipekit: the recipe manager behind `recipes/bin/recipe` and the /recipes skill.

Modules:
    model      the recipe JSON contract, the Cooking for Engineers tree, validation
    grid       Cooking for Engineers HTML tables through recipe_grid's layout engine
    note       vault notes under <vault>/Recipes/: sections, hashes, the data block
    card       the Console's ```recipe fence, built from a note
    scale      quantity scaling and the leading-quantity split
    vegan      animal-product check (bivalve-inclusive)
    nutrition  kcal and protein per serving from USDA FoodData Central
    importer   a recipe from a URL, through schema.org JSON-LD
"""
