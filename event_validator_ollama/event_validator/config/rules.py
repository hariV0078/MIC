"""Hardcoded validation rules and scoring weights."""
from typing import Dict, List, Tuple


# Theme Validation - 40 points total
THEME_RULES: List[Tuple[str, int]] = [
    ("Title matches theme", 20),
    ("Level matches duration", 10),
    ("Participants reported > 15", 10),
]

# PDF Test - 20 points total
PDF_RULES: List[Tuple[str, int]] = [
    ("PDF title matches metadata", 7),
    ("Expert details present", 7),
    ("Objectives and learning align", 6),
]

# Image Test - 20 points total
IMAGE_RULES: List[Tuple[str, int]] = [
    ("GeoTag present", 5),
    ("Banner/Poster visible", 5),
    ("Event scene is real activity", 5),
    ("15+ participants visible", 5),
]

# Similarity/Duplicate Test - 20 points total
# Note: Fail results in -10 points.
SIMILARITY_RULES: List[Tuple[str, int]] = [
    ("Duplicate image check", 10),
    ("Duplicate title check", 10),
]

# Total points: 100 based on user input
TOTAL_POINTS = 100

# Acceptance threshold - 60% of 100 is 60.
ACCEPTANCE_THRESHOLD = 60


def get_all_rules() -> Dict[str, List[Tuple[str, int]]]:
    """Get all validation rules organized by category."""
    return {
        "theme": THEME_RULES,
        "pdf": PDF_RULES,
        "image": IMAGE_RULES,
        "similarity": SIMILARITY_RULES,
    }


def get_rule_points(category: str, rule_name: str) -> int:
    """Get points for a specific rule."""
    rules = get_all_rules().get(category, [])
    for name, points in rules:
        if name == rule_name:
            return points
    return 0

