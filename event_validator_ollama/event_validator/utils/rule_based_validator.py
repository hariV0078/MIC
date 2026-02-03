"""Rule-based theme validation using deterministic keyword overlap logic."""
import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing and removing special characters."""
    return re.sub(r'[^\w\s]', ' ', text.lower())


def extract_keywords(text: str, min_length: int = 3) -> Set[str]:
    """
    Extract meaningful keywords from text (length >= min_length).
    Filters out common stop words that don't carry meaning.
    """
    normalized = normalize_text(text)
    words = normalized.split()
    
    # Comprehensive stop word list - filter out meaningless words
    stop_words = {
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'has', 'was', 'been', 
        'this', 'that', 'with', 'from', 'have', 'more', 'will', 'when', 'about', 'into',
        'session', 'on', 'new', 'emerging', 'our', 'their', 'which', 'these', 'those',
        'also', 'would', 'could', 'should', 'what', 'there', 'some', 'other', 'than',
        'any', 'only', 'such', 'very', 'much', 'many', 'most', 'both', 'each', 'few'
    }
    
    keywords = {w for w in words if len(w) >= min_length and w not in stop_words}
    return keywords


def check_theme_alignment_rules(title: str, objectives: str, learning_outcomes: str, theme: str) -> Tuple[bool, str]:
    """
    Check theme alignment using FUZZY keyword substring matching.
    
    Rules:
    1. Extract meaningful words from theme (filter stop words)
    2. Check if each theme keyword appears ANYWHERE in the event text (substring search)
    3. Pass if 2+ theme keywords found in event data
    
    Returns:
        Tuple[passed: bool, reasoning: str]
    """
    # Extract theme keywords (filter stop words)
    theme_keywords = extract_keywords(theme, min_length=3)
    
    # Combine all event data and normalize for substring search
    event_text = f"{title} {objectives} {learning_outcomes}"
    clean_event_text = normalize_text(event_text)  # Lowercase, remove special chars
    
    # FUZZY MATCHING: Check if each keyword appears ANYWHERE in the text
    matches = [kw for kw in theme_keywords if kw in clean_event_text]
    
    if not theme_keywords:
        return True, "Theme has no meaningful keywords - auto-pass"
    
    # DETERMINISTIC PASS RULE: 2+ keyword matches
    if len(matches) >= 2:
        reasoning = f"Found {len(matches)} matching keywords: {', '.join(sorted(matches)[:5])}"
        logger.info(f"Theme alignment PASS: {reasoning}")
        return True, reasoning
    else:
        reasoning = f"Only {len(matches)} matching keyword(s) found (need 2+): {', '.join(matches) if matches else 'none'}"
        logger.warning(f"Theme alignment FAIL: {reasoning}")
        return False, reasoning


def check_objectives_alignment_rules(pdf_objectives: str, expected_objectives: str) -> Tuple[bool, str]:
    """
    Check if PDF objectives align with expected using deterministic keyword overlap.
    
    Rules:
    1. Extract keywords from both
    2. If 3+ keywords match, PASS
    3. If 30%+ overlap (relative to expected), PASS
    
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
    
    # DETERMINISTIC PASS RULE: 3+ matches OR 30%+ overlap
    if len(overlap) >= 3 or overlap_pct >= 30:
        reasoning = f"Objectives overlap: {len(overlap)} keywords ({overlap_pct:.0f}%) - {', '.join(sorted(list(overlap)[:3]))}"
        return True, reasoning
    else:
        reasoning = f"Objectives weak overlap: {len(overlap)} keywords ({overlap_pct:.0f}%), need 3+ or 30%"
        return False, reasoning
