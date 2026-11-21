"""Controls for the ingredient color screen (shopping/shoptools/labels.py). No network.

Ingredient strings are trimmed from real labels read 2026-11-21 (USDA FDC branded records,
Walmart and Amazon panels, manufacturer pages).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shopping"))

from shoptools import labels  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    # Declared colors, certified and exempt (21 CFR 74 and 73).
    ("Water, Citric Acid, Sucralose, Red 40, Blue 1", "COLOR"),
    ("Water, Citric Acid, Yellow #5, Sodium Benzoate", "COLOR"),
    ("Purified water, citric acid, fruit juice (color), natural stevia extract", "COLOR"),
    ("Water, clarified lime juice concentrate, natural flavor, vegetable juices (color)", "COLOR"),
    ("Water, propylene glycol, natural flavor, beta carotene (color), sodium citrate", "COLOR"),
    ("Water, caramel color, malic acid, natural flavor, black tea", "COLOR"),
    ("Citric acid, color blend (carrot concentrate and hibiscus concentrate)", "COLOR"),
    # Phrases that mention color without adding one.
    ("Water, citric acid, natural flavors, calcium disodium EDTA (to protect color)", "CLEAR"),
    ("Citric acid, sucralose, natural flavor. No artificial colors.", "CLEAR"),
    # Colorless formulas.
    ("Propylene glycol, water, natural flavor", "CLEAR"),
    ("Crystallized lemon [citric acid, lemon oil, lemon juice]", "CLEAR"),
    ("Water, Propylene Glycol, Malic Acid, Citric Acid, Sucralose, Natural Flavor", "CLEAR"),
    # Pigmented ingredients with no declared color.
    ("Water, cranberry juice concentrate, sucralose", "TINT-RISK"),
    ("Orange pekoe and pekoe cut black teas, maltodextrin, sucralose", "TINT-RISK"),
    ("", "NO-INGREDIENTS"),
])
def test_classify(text, expected):
    assert labels.classify(text)[0] == expected


def test_haze_is_reported_but_not_a_color():
    verdict, hits = labels.classify("Water, citric acid, gum arabic, sucrose acetate isobutyrate")
    assert verdict == "CLEAR"
    assert "gum arabic" in hits["haze"]


def test_describe_names_the_hit():
    assert "red 40" in labels.describe("Water, Red 40")
