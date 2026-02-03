"""Regex-based participant count extractor with aggressive summation."""
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def extract_participant_count_regex(pdf_text: str) -> Tuple[int, str]:
    """
    Extract participant count using AGGRESSIVE regex summation.
    
    Captures ANY number near participant-related keywords and sums them all.
    This ensures "100 students" + "15 faculty" = 115 total.
    
    Returns:
        Tuple[total_count, evidence_string]
    """
    # AGGRESSIVE patterns - capture numbers BEFORE or AFTER keywords
    patterns = [
        r'(\d+)\s*(?:student|students)',           # "100 students"
        r'(\d+)\s*(?:faculty|faculties)',          # "15 faculty"
        r'(\d+)\s*(?:participant|participants)',   # "50 participants"
        r'(\d+)\s*(?:attendee|attendees)',         # "30 attendees"
        r'(\d+)\s*(?:trainee|trainees|learner|learners)',
        r'(\d+)\s*(?:people|persons|individuals)',
        r'(\d+)\s+(?:UG|PG|undergraduate|postgraduate)',
        r'(?:student|faculty|participant|attendee)s?\s*[:\-]?\s*(\d+)',  # "Students: 100"
        r'(?:total|overall|number)\s*[:\-]?\s*(\d+)',  # "Total: 115"
        r'(?:number of (?:student|faculty|participant)s?)\s*[:\-]?\s*(\d+)',
    ]
    
    found_numbers = []
    evidence_parts = []
    seen_contexts = set()  # Avoid double-counting same context
    
    pdf_lower = pdf_text.lower()
    
    for pattern in patterns:
        matches = re.finditer(pattern, pdf_lower, re.IGNORECASE)
        for match in matches:
            number = int(match.group(1))
            
            # Get context to avoid double-counting
            context_start = max(0, match.start() - 30)
            context_end = min(len(pdf_text), match.end() + 30)
            context = pdf_text[context_start:context_end].strip().replace('\n', ' ')
            
            # Avoid duplicate contexts (same number mentioned multiple times)
            context_key = f"{number}_{match.start() // 50}"  # Group by 50-char blocks
            if context_key not in seen_contexts:
                seen_contexts.add(context_key)
                found_numbers.append(number)
                evidence_parts.append(f"{number} ('{context[:40]}...')")
    
    if found_numbers:
        total = sum(found_numbers)
        evidence = "; ".join(evidence_parts[:4])  # Limit to first 4 matches
        logger.info(f"Regex extracted participants: {total} from {len(found_numbers)} matches: {found_numbers}")
        return total, evidence
    
    logger.warning("Regex participant extraction found no matches")
    return 0, "No participant numbers found in PDF"
