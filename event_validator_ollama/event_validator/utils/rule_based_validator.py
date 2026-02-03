"""Rule-based theme validation using deterministic keyword overlap logic."""
import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)

# Semantic concept mapping - related terms that should be treated as matching
THEME_CONCEPT_MAP = {
    # Innovation & Design Thinking related
    'innovation': {'ai', 'artificial', 'intelligence', 'technology', 'technological', 'revolution', 'emerging', 'learning', 'machine', 'automation', 'digital', 'smart', 'creative', 'problem', 'solving'},
    'design': {'thinking', 'creative', 'solution', 'prototype', 'ideation', 'brainstorm', 'user', 'experience'},
    'thinking': {'reasoning', 'perception', 'cognitive', 'learning', 'problem', 'solving', 'analytical'},
    
    # Technology/AI related
    'technology': {'ai', 'artificial', 'intelligence', 'innovation', 'digital', 'automation', 'computer', 'software', 'hardware'},
    'artificial': {'intelligence', 'ai', 'machine', 'learning', 'automation', 'computer'},
    'intelligence': {'ai', 'artificial', 'machine', 'learning', 'reasoning', 'perception', 'cognitive'},
    
    # Entrepreneurship related
    'entrepreneurship': {'startup', 'business', 'venture', 'innovation', 'idea', 'founder', 'incubation'},
    'startup': {'entrepreneurship', 'business', 'venture', 'innovation', 'incubation', 'funding'},
    
    # IPR related
    'ipr': {'patent', 'intellectual', 'property', 'copyright', 'trademark', 'innovation'},
    'patent': {'ipr', 'intellectual', 'property', 'innovation', 'invention'},
}


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


def expand_with_concepts(keywords: Set[str]) -> Set[str]:
    """Expand keywords with semantically related concepts."""
    expanded = set(keywords)
    for kw in keywords:
        if kw in THEME_CONCEPT_MAP:
            expanded.update(THEME_CONCEPT_MAP[kw])
    return expanded


def check_theme_alignment_rules(title: str, objectives: str, learning_outcomes: str, theme: str) -> Tuple[bool, str]:
    """
    Check theme alignment using FUZZY keyword matching with semantic concept expansion.
    
    Rules:
    1. Extract keywords from theme and expand with semantic synonyms
    2. Check if theme keywords (or their synonyms) appear in event text
    3. Pass if 2+ theme-related keywords found in event data
    
    Returns:
        Tuple[passed: bool, reasoning: str]
    """
    # Extract and EXPAND theme keywords with semantic concepts
    theme_keywords = extract_keywords(theme, min_length=3)
    expanded_theme_keywords = expand_with_concepts(theme_keywords)
    
    # Combine all event data and normalize for substring search
    event_text = f"{title} {objectives} {learning_outcomes}"
    clean_event_text = normalize_text(event_text)
    event_keywords = extract_keywords(event_text, min_length=2)  # Allow 2-char like "AI"
    
    # FUZZY MATCHING: Check for theme keywords OR their semantic synonyms
    direct_matches = [kw for kw in theme_keywords if kw in clean_event_text]
    semantic_matches = [kw for kw in expanded_theme_keywords if kw in event_keywords]
    
    all_matches = set(direct_matches) | set(semantic_matches)
    
    if not theme_keywords:
        return True, "Theme has no meaningful keywords - auto-pass"
    
    # DETERMINISTIC PASS RULE: 2+ keyword matches (direct or semantic)
    if len(all_matches) >= 2:
        reasoning = f"Found {len(all_matches)} matching keywords: {', '.join(sorted(list(all_matches)[:6]))}"
        logger.info(f"Theme alignment PASS: {reasoning}")
        return True, reasoning
    else:
        reasoning = f"Only {len(all_matches)} matching keyword(s) found (need 2+): {', '.join(all_matches) if all_matches else 'none'}"
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
