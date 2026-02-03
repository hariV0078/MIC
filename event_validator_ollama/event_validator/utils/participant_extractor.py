"""Regex-based participant count extractor for hybrid validation."""
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def extract_participant_count_regex(pdf_text: str) -> Tuple[int, str]:
    """
    Extract participant count using regex pattern matching.
    
    Searches for patterns like:
    - "100 students"
    - "15 faculty"
    - "50 participants"
    
    Returns:
        Tuple[total_count, evidence_string]
    """
    # Common participant-related keywords - more flexible patterns
    patterns = [
        r'(\d+)\s*(?:student|students)',
        r'(\d+)\s*(?:faculty|faculties)',
        r'(\d+)\s*(?:participant|participants)',
        r'(\d+)\s*(?:attendee|attendees)',
        r'(\d+)\s*(?:trainee|trainees|learner|learners)',
        r'(?:total|overall|number)[\s:]+(\d+)',
        r'(\d+)\s*(?:people|persons|individuals)',
        r'(?:students|faculty|participants)[\s:]+(\d+)',  # Reverse pattern
        r'(\d+)\s+(?:UG|PG|undergraduate|postgraduate)',  # Academic formats
    ]
    
    found_numbers = []
    evidence_parts = []
    
    pdf_lower = pdf_text.lower()
    
    for pattern in patterns:
        matches = re.finditer(pattern, pdf_lower, re.IGNORECASE)
        for match in matches:
            number = int(match.group(1))
            context_start = max(0, match.start() - 20)
            context_end = min(len(pdf_text), match.end() + 20)
            context = pdf_text[context_start:context_end].strip()
            
            found_numbers.append(number)
            evidence_parts.append(f"{number} ({context})")
    
    if found_numbers:
        total = sum(found_numbers)
        evidence = "; ".join(evidence_parts[:3])  # Limit to first 3 matches
        logger.info(f"Regex extracted participants: {total} from {len(found_numbers)} matches")
        return total, evidence
    
    logger.warning("Regex participant extraction found no matches")
    return 0, "No participant numbers found"
