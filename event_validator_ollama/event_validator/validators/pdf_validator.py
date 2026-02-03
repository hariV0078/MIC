"""PDF validation using hardcoded rules and Gemini."""
import logging
from typing import List, Optional
import hashlib

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def validate_pdf_title_match(
    submission: EventSubmission,
    ollama_client: OllamaClient
) -> ValidationResult:
    """Check if PDF title matches metadata."""
    rule_name, points = PDF_RULES[0]
    
    row_data = submission.row_data
    expected_title = str(row_data.get('Title', '')).strip()
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF text not extracted"
        )
    
    pdf_title = submission.pdf_data.title or ""
    pdf_text = submission.pdf_data.text[:500]  # First 500 chars for title search
    
    # Use Ollama for fuzzy title matching
    consistency = ollama_client.check_pdf_consistency(
        pdf_text=submission.pdf_data.text,
        expected_title=expected_title,
        expected_objectives=None,
        expected_learning_outcomes=None,
        expected_participants=None
    )
    
    if consistency.get("title_match", False):
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"PDF title does not match expected title: {expected_title}"
        )


def validate_expert_details(
    submission: EventSubmission,
    ollama_client: Optional[OllamaClient] = None
) -> ValidationResult:
    """Check if expert details are present in PDF."""
    rule_name, points = PDF_RULES[1]
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF text not extracted"
        )
    
    pdf_text = submission.pdf_data.text.lower()
    
    # Look for expert-related keywords
    expert_keywords = [
        'expert', 'speaker', 'facilitator', 'instructor', 'trainer',
        'resource person', 'keynote', 'presenter', 'panelist'
    ]
    
    # Look for name patterns (capitalized words, titles)
    has_expert_mention = any(keyword in pdf_text for keyword in expert_keywords)
    
    # Check for name-like patterns (e.g., "Dr. Name", "Prof. Name")
    import re
    name_patterns = [
        r'\b(Dr|Prof|Professor|Mr|Mrs|Ms|Miss)\.?\s+[A-Z][a-z]+',
        r'\b[A-Z][a-z]+\s+[A-Z][a-z]+',  # First Last
    ]
    has_name_pattern = any(re.search(pattern, submission.pdf_data.text) for pattern in name_patterns)
    
    if has_expert_mention or has_name_pattern:
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Expert details not found in PDF"
        )


def validate_learning_outcomes_align(
    submission: EventSubmission,
    ollama_client: OllamaClient
) -> ValidationResult:
    """Check if learning outcomes align."""
    rule_name, points = PDF_RULES[2]
    
    row_data = submission.row_data
    expected_learning = str(row_data.get('Learning Outcomes', '')).strip()
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF text not extracted"
        )
    
    # Use Groq for semantic alignment
    consistency = ollama_client.check_pdf_consistency(
        pdf_text=submission.pdf_data.text,
        expected_title=None,
        expected_objectives=None,
        expected_learning_outcomes=expected_learning,
        expected_participants=None
    )
    
    if consistency.get("learning_match", False):
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Learning outcomes in PDF do not align with expected outcomes"
        )


def validate_objectives_match(
    submission: EventSubmission,
    ollama_client: OllamaClient
) -> ValidationResult:
    """Check if objectives match."""
    rule_name, points = PDF_RULES[3]
    
    row_data = submission.row_data
    expected_objectives = str(row_data.get('Objectives', '')).strip()
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF text not extracted"
        )
    
    # Use Groq for semantic alignment
    consistency = ollama_client.check_pdf_consistency(
        pdf_text=submission.pdf_data.text,
        expected_title=None,
        expected_objectives=expected_objectives,
        expected_learning_outcomes=None,
        expected_participants=None
    )
    
    if consistency.get("objectives_match", False):
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Objectives in PDF do not match expected objectives"
        )


def validate_participant_info_match(
    submission: EventSubmission,
    ollama_client: OllamaClient
) -> ValidationResult:
    """Check if participant info matches."""
    rule_name, points = PDF_RULES[4]
    
    row_data = submission.row_data
    expected_participants = None
    try:
        participants_str = str(row_data.get('Participants', '0')).strip()
        expected_participants = int(float(participants_str))
    except (ValueError, TypeError):
        pass
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF text not extracted"
        )
    
    # Use Groq for participant validation
    consistency = ollama_client.check_pdf_consistency(
        pdf_text=submission.pdf_data.text,
        expected_title=None,
        expected_objectives=None,
        expected_learning_outcomes=None,
        expected_participants=expected_participants
    )
    
    if consistency.get("participants_valid", False):
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"PDF participant information does not match expected (needs 15+ participants)"
        )


def _is_mic_event(submission: EventSubmission) -> bool:
    """Check if this is a MIC event - automatically accept PDF validation."""
    row_data = submission.row_data
    original_data = getattr(submission, '_original_row_data', row_data)
    
    # Check multiple possible identifiers for MIC events
    event_type = str(row_data.get('Event Type', '')).strip().upper()
    theme = str(row_data.get('Theme', '')).strip().upper()
    title = str(row_data.get('Title', '')).strip().upper()
    activity_name = str(original_data.get('activity_name', '')).strip().upper()
    
    # Check if any field contains "MIC" (case-insensitive)
    mic_indicators = ['MIC', 'MIC-IIC', 'MIC IIC']
    for indicator in mic_indicators:
        if (indicator in event_type or 
            indicator in theme or 
            indicator in title or 
            indicator in activity_name):
            return True
    
    return False


def validate_pdf(submission: EventSubmission, ollama_client: OllamaClient) -> List[ValidationResult]:
    """
    OPTIMIZED: Run all PDF validations using a single unified API call.
    This replaces 5 separate calls with 1 call, providing ~3-4x speedup.
    
    SPECIAL CASE: MIC events automatically pass all PDF validations.
    """
    results = []
    
    # SPECIAL CASE: MIC events - automatically accept all PDF validations
    if _is_mic_event(submission):
        logger.info("MIC event detected - automatically accepting all PDF validations")
        for rule_name, points in PDF_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=True,
                points_awarded=points,
                message="MIC event - PDF validation auto-accepted"
            ))
        return results
    
    # Pre-check: If PDF data is missing, return all failures immediately (pre-scoring gate)
    if not submission.pdf_data or not submission.pdf_data.text:
        logger.warning("PDF text not extracted - skipping all PDF validations")
        for rule_name, points in PDF_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="PDF text not extracted"
            ))
        return results
    
    # Get expected values from submission
    row_data = submission.row_data
    expected_title = str(row_data.get('Title', '')).strip()
    expected_objectives = str(row_data.get('Objectives', '')).strip()
    expected_learning_outcomes = str(row_data.get('Learning Outcomes', '')).strip()
    expected_participants = None
    try:
        participants_str = str(row_data.get('Participants', '0')).strip()
        expected_participants = int(float(participants_str))
    except (ValueError, TypeError):
        pass
    
    # Generate PDF content hash for caching
    pdf_text = submission.pdf_data.text
    pdf_hash = hashlib.sha256(pdf_text.encode('utf-8')).hexdigest()[:16]  # Use first 16 chars for cache key
    
    # Pre-scoring gate: Quick heuristic checks before AI call
    # If basic keywords are missing, we can skip some validations
    pdf_text_lower = pdf_text.lower()
    has_expert_keywords = any(kw in pdf_text_lower for kw in [
        'expert', 'speaker', 'facilitator', 'instructor', 'trainer',
        'resource person', 'keynote', 'presenter', 'panelist'
    ])
    
    # Single unified API call for all PDF validations
    logger.info("Running unified PDF validation (single API call for all 5 checks)")
    validation_results = ollama_client.validate_pdf_comprehensive(
        pdf_text=pdf_text,
        expected_title=expected_title if expected_title else None,
        expected_objectives=expected_objectives if expected_objectives else None,
        expected_learning_outcomes=expected_learning_outcomes if expected_learning_outcomes else None,
        expected_participants=expected_participants,
        pdf_hash=pdf_hash
    )
    
    # Get event_driven for special handling
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = original_data.get('event_driven')
    try:
        event_driven = int(event_driven) if event_driven is not None else None
    except (ValueError, TypeError):
        event_driven = None
    
    # Map unified results to individual validation results
    # Rule 0: PDF title matches metadata (7 points)
    rule_name, points = PDF_RULES[0]
    title_match = validation_results.get("title_match", False)
    reasoning = validation_results.get("reasoning", "")
    results.append(ValidationResult(
        criterion=rule_name,
        passed=title_match,
        points_awarded=points if title_match else 0,
        message="" if title_match else f"PDF title does not match expected: {expected_title}. Reason: {reasoning}"
    ))
    
    # SPECIAL CASE: For event_driven=3, if title doesn't match, fail ALL PDF validations
    if event_driven == 3 and not title_match:
        logger.warning(f"Event driven 3: Title mismatch detected - failing all PDF validations")
        # Rule 1: Expert details present (7 points) - FAIL
        rule_name, points = PDF_RULES[1]
        results.append(ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF title mismatch - all PDF validations failed for event_driven=3"
        ))
        # Rule 2: Learning outcomes align (3 points) - FAIL
        rule_name, points = PDF_RULES[2]
        results.append(ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF title mismatch - all PDF validations failed for event_driven=3"
        ))
        # Rule 3: Objectives match (3 points) - FAIL
        rule_name, points = PDF_RULES[3]
        results.append(ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF title mismatch - all PDF validations failed for event_driven=3"
        ))
        # Rule 4: Participant info matches (5 points) - FAIL
        rule_name, points = PDF_RULES[4]
        results.append(ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="PDF title mismatch - all PDF validations failed for event_driven=3"
        ))
        return results
    
    # Rule 1: Expert details present (7 points)
    # Use heuristic check first, then AI result
    rule_name, points = PDF_RULES[1]
    expert_passed = validation_results.get("expert_details_present", False) or has_expert_keywords
    results.append(ValidationResult(
        criterion=rule_name,
        passed=expert_passed,
        points_awarded=points if expert_passed else 0,
        message="" if expert_passed else f"Expert details not found in PDF. Evidence: {reasoning}"
    ))
    
    # Rule 2: Learning outcomes align (3 points)
    # SPECIAL CASE: If title doesn't match, learning outcomes should also fail
    rule_name, points = PDF_RULES[2]
    learning_passed = validation_results.get("learning_outcomes_align", False) and title_match
    results.append(ValidationResult(
        criterion=rule_name,
        passed=learning_passed,
        points_awarded=points if learning_passed else 0,
        message="" if learning_passed else (f"Learning outcomes in PDF do not align with expected outcomes. Reason: {reasoning}" if title_match else "PDF title mismatch - learning outcomes validation failed")
    ))
    
    # Rule 3: Objectives match (3 points)
    # Use RULE-BASED validation instead of AI
    rule_name, points = PDF_RULES[3]
    
    from event_validator.utils.rule_based_validator import check_objectives_alignment_rules
    
    # Extract objectives from PDF (first 2000 chars likely contain them)
    pdf_objectives_section = pdf_text[:2000]
    objectives_aligned, obj_reasoning = check_objectives_alignment_rules(
        pdf_objectives=pdf_objectives_section,
        expected_objectives=expected_objectives
    )
    
    results.append(ValidationResult(
        criterion=rule_name,
        passed=objectives_aligned,
        points_awarded=points if objectives_aligned else 0,
        message="" if objectives_aligned else f"Objectives mismatch. {obj_reasoning}"
    ))
    
    # Rule 4: Participant info matches (5 points)
    # HYBRID APPROACH: Try regex first, then use AI result as fallback
    rule_name, points = PDF_RULES[4]
    
    # Import regex extractor
    from event_validator.utils.participant_extractor import extract_participant_count_regex
    
    # Try regex extraction first (more reliable for numbers)
    regex_count, regex_evidence = extract_participant_count_regex(pdf_text)
    
    if regex_count >= 15:
        # Regex found sufficient participants - trust it
        logger.info(f"Regex participant check PASSED: {regex_count} >= 15")
        results.append(ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        ))
    else:
        # Regex didn't find enough - check AI result as fallback
        ai_passed = validation_results.get("participants_valid", False)
        if ai_passed:
            logger.info("AI participant check PASSED (regex found insufficient)")
            results.append(ValidationResult(
                criterion=rule_name,
                passed=True,
                points_awarded=points,
                message=""
            ))
        else:
            # Both regex and AI failed
            combined_evidence = f"Regex: {regex_evidence}; AI: {reasoning}" if regex_evidence else reasoning
            logger.warning(f"Participant check FAILED. Regex count: {regex_count}, AI: {ai_passed}")
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message=f"PDF participant information does not match expected (needs 15+ participants). Found: {combined_evidence}"
            ))
    
    logger.debug(f"PDF validation complete. Reasoning: {validation_results.get('reasoning', 'N/A')}")
    
    return results

