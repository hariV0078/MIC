"""Hardcoded validation rules and scoring weights."""
from typing import Dict, List, Tuple


# Theme Validation - 40 points total
THEME_RULES: List[Tuple[str, int]] = [
    ("Title/Objectives/Learning align to theme", 10),
    ("Level matches duration", 11),
    ("Participants reported > 15", 12),
    ("Year alignment (financial vs academic)", 7),
]

# PDF Test - 25 points total
PDF_RULES: List[Tuple[str, int]] = [
    ("PDF title matches metadata", 7),
    ("Expert details present", 7),
    ("Learning outcomes align", 3),
    ("Objectives match", 3),
    ("Participant info matches", 5),
]

# Image Test - 20 points total
IMAGE_RULES: List[Tuple[str, int]] = [
    ("GeoTag present", 6),
    ("Banner/Poster visible", 2),
    ("Event scene is real activity", 3),
    ("Event mode matches (online/offline)", 5),
    ("15+ participants visible", 4),
]

# Similarity Test - 15 points total
SIMILARITY_RULES: List[Tuple[str, int]] = [
    ("Duplicate photo detection (filesystem)", 15),
]

# Total points: 100
TOTAL_POINTS = 100

# Acceptance threshold
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

