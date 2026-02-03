"""Rule-based theme validation using keyword overlap logic."""
import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing and removing special characters."""
    return re.sub(r'[^\w\s]', ' ', text.lower())


def extract_keywords(text: str, min_length: int = 3) -> Set[str]:
    """Extract meaningful keywords from text (length >= min_length)."""
    normalized = normalize_text(text)
    words = normalized.split()
    # Filter out common stop words
    stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'has', 'was', 'been', 'this', 'that', 'with', 'from', 'have', 'more', 'will', 'when'}
    keywords = {w for w in words if len(w) >= min_length and w not in stop_words}
    return keywords


def check_theme_alignment_rules(title: str, objectives: str, learning_outcomes: str, theme: str) -> Tuple[bool, str]:
    """
    Check theme alignment using rule-based keyword overlap.
    
    Rules:
    1. Extract keywords from theme (length >= 3)
    2. Extract keywords from event data (title + objectives + outcomes)
    3. Calculate overlap percentage
    4. If overlap >= 20% OR any 2+ theme keywords found, PASS
    
    Returns:
        Tuple[passed: bool, reasoning: str]
    """
    # Extract keywords
    theme_keywords = extract_keywords(theme, min_length=3)
    
    # Combine all event data
    event_text = f"{title} {objectives} {learning_outcomes}"
    event_keywords = extract_keywords(event_text, min_length=3)
    
    # Find overlap
    overlap = theme_keywords & event_keywords
    
    if not theme_keywords:
        return True, "Theme has no keywords - auto-pass"
    
    # Calculate overlap percentage
    overlap_pct = (len(overlap) / len(theme_keywords)) * 100
    
    # Decision logic
    if len(overlap) >= 2 or overlap_pct >= 20:
        reasoning = f"Found {len(overlap)} matching keywords: {', '.join(list(overlap)[:5])}"
        logger.info(f"Theme alignment PASS: {reasoning}")
        return True, reasoning
    else:
        reasoning = f"Only {len(overlap)} matching keywords found (need 2+): {', '.join(overlap) if overlap else 'none'}"
        logger.warning(f"Theme alignment FAIL: {reasoning}")
        return False, reasoning


def check_objectives_alignment_rules(pdf_objectives: str, expected_objectives: str) -> Tuple[bool, str]:
    """
    Check if PDF objectives align with expected using keyword overlap.
    
    Rules:
    1. Extract keywords from both
    2. If 30%+ overlap, PASS
    3. If any 3+ keywords match, PASS
    
    Returns:
        Tuple[passed: bool, reasoning: str]
    """
    if not expected_objectives or not pdf_objectives:
        return True, "No objectives to compare - auto-pass"
    
    expected_kw = extract_keywords(expected_objectives, min_length=3)
    pdf_kw = extract_keywords(pdf_objectives, min_length=3)
    
    overlap = expected_kw & pdf_kw
    
    if not expected_kw:
        return True, "Expected objectives empty - auto-pass"
    
    overlap_pct = (len(overlap) / len(expected_kw)) * 100
    
    if len(overlap) >= 3 or overlap_pct >= 30:
        reasoning = f"Objectives overlap: {len(overlap)} keywords ({overlap_pct:.0f}%)"
        return True, reasoning
    else:
        reasoning = f"Objectives weak overlap: {len(overlap)} keywords ({overlap_pct:.0f}%), need 3+ or 30%"
        return False, reasoning
