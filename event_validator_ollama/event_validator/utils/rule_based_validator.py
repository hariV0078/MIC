"""Rule-based theme validation using deterministic keyword overlap logic."""
import re
import logging
from typing import Tuple, Set

logger = logging.getLogger(__name__)

# Semantic concept mapping - related terms that should be treated as matching
# Covers 4 themes: Entrepreneurship & Startup, Innovation & Design Thinking, 
# IPR & Technology Transfer, Pre-Incubation & Incubation Management
THEME_CONCEPT_MAP = {
    # ==========================================================================
    # THEME 1: Entrepreneurship & Startup
    # ==========================================================================
    'entrepreneurship': {
        'startup', 'business', 'venture', 'innovation', 'idea', 'founder', 'incubation',
        'enterprise', 'company', 'organization', 'industry', 'commerce', 'trade',
        'market', 'customer', 'revenue', 'profit', 'growth', 'scaling', 'pitch',
        'investor', 'funding', 'investment', 'capital', 'finance', 'seed', 'angel',
        'accelerator', 'mentor', 'mentoring', 'ecosystem', 'hub', 'center', 'centre',
        'development', 'skill', 'training', 'workshop', 'session', 'program', 'programme'
    },
    'startup': {
        'entrepreneurship', 'business', 'venture', 'innovation', 'incubation', 'funding',
        'founder', 'cofounder', 'ceo', 'cto', 'product', 'service', 'solution',
        'market', 'customer', 'user', 'growth', 'scaling', 'pitch', 'investor',
        'accelerator', 'ecosystem', 'hub', 'technology', 'tech', 'digital'
    },
    'business': {
        'entrepreneurship', 'startup', 'venture', 'enterprise', 'company', 'industry',
        'commerce', 'trade', 'market', 'customer', 'revenue', 'profit', 'growth',
        'management', 'strategy', 'planning', 'development', 'innovation'
    },
    'venture': {
        'entrepreneurship', 'startup', 'business', 'funding', 'investment', 'capital',
        'investor', 'finance', 'growth', 'scaling', 'innovation'
    },
    'founder': {
        'entrepreneurship', 'startup', 'cofounder', 'ceo', 'leader', 'visionary',
        'innovator', 'creator', 'builder', 'mentor'
    },
    
    # ==========================================================================
    # THEME 2: Innovation & Design Thinking
    # ==========================================================================
    'innovation': {
        'ai', 'artificial', 'intelligence', 'technology', 'technological', 'revolution',
        'emerging', 'learning', 'machine', 'automation', 'digital', 'smart', 'creative',
        'problem', 'solving', 'solution', 'idea', 'ideation', 'prototype', 'design',
        'thinking', 'research', 'development', 'advancement', 'progress', 'future',
        'disruption', 'disruptive', 'breakthrough', 'invention', 'inventive', 'novelty',
        'entrepreneurship', 'startup', 'incubation', 'industry', 'manufacturing',
        'medtech', 'healthcare', 'biotech', 'biotechnology', 'pharma', 'pharmaceutical',
        'industrial', 'visit', 'field', 'exposure', 'facility', 'zone', 'park', 'hub'
    },
    'design': {
        'thinking', 'creative', 'solution', 'prototype', 'ideation', 'brainstorm',
        'user', 'experience', 'ux', 'ui', 'interface', 'product', 'service',
        'empathy', 'define', 'ideate', 'test', 'iterate', 'innovation', 'problem',
        'solving', 'human', 'centered', 'centric'
    },
    'thinking': {
        'design', 'reasoning', 'perception', 'cognitive', 'learning', 'problem',
        'solving', 'analytical', 'critical', 'creative', 'innovation', 'ideation',
        'brainstorm', 'solution', 'approach', 'methodology', 'framework'
    },
    'creative': {
        'innovation', 'design', 'thinking', 'ideation', 'brainstorm', 'solution',
        'problem', 'solving', 'artistic', 'imagination', 'novelty', 'original'
    },
    'prototype': {
        'innovation', 'design', 'product', 'mvp', 'minimum', 'viable', 'development',
        'testing', 'iteration', 'model', 'demo', 'demonstration', 'proof', 'concept'
    },
    
    # ==========================================================================
    # THEME 3: IPR & Technology Transfer
    # ==========================================================================
    'ipr': {
        'patent', 'intellectual', 'property', 'copyright', 'trademark', 'innovation',
        'invention', 'rights', 'protection', 'filing', 'registration', 'license',
        'licensing', 'royalty', 'transfer', 'technology', 'commercialization'
    },
    'patent': {
        'ipr', 'intellectual', 'property', 'innovation', 'invention', 'rights',
        'protection', 'filing', 'registration', 'claim', 'prior', 'art', 'novelty',
        'utility', 'design', 'provisional', 'grant', 'application'
    },
    'intellectual': {
        'property', 'ipr', 'patent', 'copyright', 'trademark', 'rights', 'protection',
        'innovation', 'invention', 'creative', 'original'
    },
    'property': {
        'intellectual', 'ipr', 'patent', 'copyright', 'trademark', 'rights',
        'protection', 'ownership', 'asset'
    },
    'technology': {
        'transfer', 'innovation', 'ai', 'artificial', 'intelligence', 'digital',
        'automation', 'computer', 'software', 'hardware', 'development', 'research',
        'advancement', 'emerging', 'disruptive', 'breakthrough', 'medtech', 'biotech',
        'industrial', 'manufacturing', 'industry', 'facility', 'zone', 'park'
    },
    'transfer': {
        'technology', 'knowledge', 'commercialization', 'licensing', 'collaboration',
        'partnership', 'industry', 'academia', 'research', 'innovation'
    },
    'copyright': {
        'ipr', 'intellectual', 'property', 'rights', 'protection', 'creative',
        'original', 'author', 'work', 'publication'
    },
    'trademark': {
        'ipr', 'intellectual', 'property', 'brand', 'logo', 'identity', 'protection',
        'registration', 'rights'
    },
    
    # ==========================================================================
    # THEME 4: Pre-Incubation & Incubation Management
    # ==========================================================================
    'incubation': {
        'startup', 'entrepreneurship', 'innovation', 'business', 'venture', 'industry',
        'development', 'preincubation', 'pre', 'accelerator', 'hub', 'center', 'centre',
        'ecosystem', 'mentor', 'mentoring', 'coaching', 'guidance', 'support',
        'funding', 'investment', 'seed', 'grant', 'facility', 'workspace', 'coworking',
        'management', 'program', 'programme', 'cohort', 'batch', 'selection',
        'medtech', 'healthcare', 'biotech', 'industrial', 'manufacturing', 'zone', 'park'
    },
    'preincubation': {
        'incubation', 'startup', 'entrepreneurship', 'idea', 'ideation', 'validation',
        'concept', 'prototype', 'mvp', 'mentoring', 'coaching', 'training', 'workshop',
        'bootcamp', 'program', 'programme'
    },
    'pre': {
        'incubation', 'preincubation', 'startup', 'idea', 'ideation', 'validation',
        'concept', 'early', 'stage'
    },
    'accelerator': {
        'incubation', 'startup', 'entrepreneurship', 'growth', 'scaling', 'funding',
        'investment', 'mentor', 'mentoring', 'program', 'programme', 'cohort', 'batch'
    },
    'management': {
        'incubation', 'business', 'startup', 'operations', 'strategy', 'planning',
        'development', 'leadership', 'administration', 'organization'
    },
    'mentor': {
        'incubation', 'entrepreneurship', 'startup', 'guidance', 'coaching', 'advice',
        'support', 'expert', 'industry', 'experience'
    },
    
    # ==========================================================================
    # Industry/Field Visits & Exposure Programs
    # ==========================================================================
    'visit': {
        'field', 'industrial', 'industry', 'exposure', 'tour', 'observation', 'learning',
        'experience', 'practical', 'hands', 'facility', 'plant', 'factory', 'company',
        'organization', 'institution', 'center', 'centre', 'zone', 'park', 'hub',
        'medtech', 'healthcare', 'biotech', 'pharma', 'manufacturing', 'production'
    },
    'field': {
        'visit', 'industrial', 'industry', 'exposure', 'tour', 'practical', 'hands',
        'experience', 'learning', 'observation', 'site', 'facility'
    },
    'industrial': {
        'visit', 'field', 'industry', 'manufacturing', 'production', 'factory', 'plant',
        'facility', 'zone', 'park', 'exposure', 'tour', 'experience', 'innovation',
        'technology', 'automation', 'engineering'
    },
    'industry': {
        'industrial', 'visit', 'field', 'manufacturing', 'production', 'business',
        'enterprise', 'company', 'sector', 'innovation', 'technology', 'incubation',
        'ecosystem', 'collaboration', 'partnership', 'academia'
    },
    'exposure': {
        'visit', 'field', 'industrial', 'industry', 'tour', 'experience', 'learning',
        'observation', 'practical', 'hands'
    },
    
    # ==========================================================================
    # Healthcare/MedTech/Biotech (for industrial visits)
    # ==========================================================================
    'medtech': {
        'medical', 'healthcare', 'health', 'clinical', 'hospital', 'biomedical',
        'diagnosis', 'treatment', 'device', 'equipment', 'technology', 'innovation',
        'incubation', 'industry', 'zone', 'park', 'facility', 'manufacturing'
    },
    'healthcare': {
        'medtech', 'medical', 'health', 'clinical', 'hospital', 'patient', 'care',
        'treatment', 'diagnosis', 'biotechnology', 'pharmaceutical', 'pharma',
        'innovation', 'technology', 'industry', 'advancing'
    },
    'medical': {
        'medtech', 'healthcare', 'health', 'clinical', 'hospital', 'patient',
        'diagnosis', 'treatment', 'device', 'equipment', 'biomedical', 'pharmaceutical'
    },
    'biotech': {
        'biotechnology', 'medtech', 'healthcare', 'medical', 'pharmaceutical', 'pharma',
        'research', 'development', 'innovation', 'technology', 'life', 'science'
    },
    'biotechnology': {
        'biotech', 'medtech', 'healthcare', 'medical', 'pharmaceutical', 'pharma',
        'research', 'development', 'innovation', 'technology', 'life', 'science'
    },
    'pharmaceutical': {
        'pharma', 'medtech', 'healthcare', 'medical', 'biotech', 'biotechnology',
        'drug', 'medicine', 'treatment', 'research', 'development', 'manufacturing'
    },
    'pharma': {
        'pharmaceutical', 'medtech', 'healthcare', 'medical', 'biotech', 'biotechnology',
        'drug', 'medicine', 'treatment', 'research', 'development', 'manufacturing'
    },
    
    # ==========================================================================
    # Facility/Zone/Park keywords (for industrial visits)
    # ==========================================================================
    'zone': {
        'industrial', 'manufacturing', 'technology', 'tech', 'innovation', 'incubation',
        'special', 'economic', 'sez', 'park', 'hub', 'facility', 'center', 'centre',
        'medtech', 'biotech', 'pharma', 'amtz'
    },
    'park': {
        'industrial', 'technology', 'tech', 'innovation', 'incubation', 'zone',
        'hub', 'facility', 'center', 'centre', 'software', 'it', 'research'
    },
    'hub': {
        'innovation', 'incubation', 'startup', 'entrepreneurship', 'technology',
        'center', 'centre', 'ecosystem', 'zone', 'park', 'facility'
    },
    'facility': {
        'industrial', 'manufacturing', 'production', 'plant', 'factory', 'zone',
        'park', 'hub', 'center', 'centre', 'visit', 'tour', 'infrastructure'
    },
    'amtz': {
        'medtech', 'medical', 'healthcare', 'health', 'technology', 'zone', 'park',
        'andhra', 'pradesh', 'incubation', 'innovation', 'industry', 'manufacturing',
        'facility', 'device', 'equipment', 'advancing', 'innovating'
    },
    
    # ==========================================================================
    # Action/Activity keywords (for better matching)
    # ==========================================================================
    'advancing': {
        'innovation', 'progress', 'development', 'growth', 'improvement', 'industry',
        'technology', 'healthcare', 'medtech'
    },
    'innovating': {
        'innovation', 'creative', 'novel', 'new', 'development', 'technology',
        'healthcare', 'medtech', 'industry'
    },
    'learning': {
        'education', 'training', 'workshop', 'session', 'skill', 'knowledge',
        'development', 'outcome', 'objective', 'experience', 'practical', 'hands'
    },
    'workshop': {
        'training', 'session', 'learning', 'skill', 'development', 'hands', 'practical',
        'entrepreneurship', 'innovation', 'design', 'thinking', 'ipr', 'incubation'
    },
    'session': {
        'workshop', 'training', 'learning', 'presentation', 'talk', 'seminar',
        'webinar', 'conference', 'event', 'program', 'programme'
    },
    'training': {
        'workshop', 'session', 'learning', 'skill', 'development', 'education',
        'program', 'programme', 'hands', 'practical'
    },
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
    
    # Combine title and learning outcomes for theme checking (exclude objectives)
    event_text = f"{title} {learning_outcomes}"
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
