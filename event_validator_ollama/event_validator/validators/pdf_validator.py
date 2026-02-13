"""PDF validation using hardcoded rules and Gemini."""
import logging
import re
from typing import List, Optional
import hashlib

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.ollama_client import OllamaClient

try:
    from thefuzz import fuzz
    FUZZ_AVAILABLE = True
except ImportError:
    fuzz = None
    FUZZ_AVAILABLE = False

logger = logging.getLogger(__name__)


def _fuzzy_match_pdf_title(pdf_text: str, expected_title: str, activity_name: str) -> bool:
    """
    Fuzzy match PDF title using first half of first page content.
    
    Steps:
    1. Extract first page text (use first chunk before page break markers)
    2. Take the first half of that text
    3. Use fuzzy matching (token_set_ratio) to compare activity_name against the content
    4. Accept if score >= 60%
    
    Returns True if the activity name fuzzy-matches the first page content.
    """
    if not pdf_text or not (expected_title or activity_name):
        return False
    
    # Use activity_name preferentially, fall back to expected_title
    search_term = activity_name.strip() if activity_name.strip() else expected_title.strip()
    if not search_term:
        return False
    
    # Extract first page content:
    # Try common page break markers first
    first_page_text = pdf_text
    page_delimiters = ['\f', '\n\n\n', '--- Page', 'Page 2']
    for delimiter in page_delimiters:
        if delimiter in pdf_text:
            first_page_text = pdf_text.split(delimiter)[0]
            break
    
    # If no delimiter found, estimate first page as first 2000 chars
    if first_page_text == pdf_text and len(pdf_text) > 2000:
        first_page_text = pdf_text[:2000]
    
    # Take first half of first page
    half_len = max(len(first_page_text) // 2, 200)  # At least 200 chars
    first_half = first_page_text[:half_len]
    
    if not first_half.strip():
        return False
    
    if not FUZZ_AVAILABLE:
        # Fallback: simple case-insensitive substring check
        logger.warning("thefuzz not available, falling back to substring match")
        return search_term.lower() in first_half.lower()
    
    # Use token_set_ratio for fuzzy matching
    # This handles word reordering and partial matches well
    score = fuzz.token_set_ratio(search_term.lower(), first_half.lower())
    logger.info(f"PDF title fuzzy match: score={score}% (threshold=60%) | "
                f"search_term='{search_term[:50]}' vs first_half='{first_half[:80]}...'")
    
    return score >= 60


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
    
    # Use Groq for fuzzy title matching
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


def validate_objectives_learning_align(
    submission: EventSubmission,
    ollama_client: OllamaClient
) -> ValidationResult:
    """Check if objectives and learning outcomes allow."""
    # Rule 2: "Objectives and learning align" (6 pts)
    rule_name, points = PDF_RULES[2]
    
    row_data = submission.row_data
    expected_learning = str(row_data.get('Learning Outcomes', '')).strip()
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
        expected_learning_outcomes=expected_learning,
        expected_participants=None
    )
    
    # Pass if EITHER learning match OR objectives match
    if consistency.get("learning_match", False) or consistency.get("objectives_match", False):
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
            message="Objectives/Learning outcomes in PDF do not align with expected values"
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
        
    theme = str(row_data.get('Theme', '')).strip()
    
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
    
    # Get event_driven for special handling
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = original_data.get('event_driven')
    try:
        event_driven = int(event_driven) if event_driven is not None else None
    except (ValueError, TypeError):
        event_driven = None
    
    # Get activity_name from original row data for fuzzy matching
    activity_name = str(original_data.get('activity_name', '')).strip()
    
    # =========================================================
    # SPECIAL CASE: event_driven=3 — strict validation flow
    # 1. Validate theme alignment (strict) → fail all if theme fails
    # 2. Compare PDF title (MUST match exactly) → fail all if title fails
    # 3. Only if both pass → run all PDF validations
    # =========================================================
    if event_driven == 3:
        logger.info("Event driven 3: Running strict validation flow (theme → title → PDF checks)")
        
        # Step 1: Strict theme alignment check
        theme_aligned = ollama_client.check_theme_alignment(
            title=activity_name or expected_title,
            theme=theme,
            objectives=expected_objectives,
            learning_outcomes=expected_learning_outcomes
        )
        
        if not theme_aligned:
            logger.warning("Event driven 3: Theme alignment FAILED - failing ALL PDF validations")
            for rule_name, points in PDF_RULES:
                results.append(ValidationResult(
                    criterion=rule_name,
                    passed=False,
                    points_awarded=0,
                    message="Theme alignment failed - all PDF validations failed for event_driven=3"
                ))
            return results
        
        logger.info("Event driven 3: Theme alignment PASSED - proceeding to title check")
        
        # Step 2: PDF title must match (using fuzzy matching with 60% threshold)
        rule_name, points = PDF_RULES[0]
        title_match = _fuzzy_match_pdf_title(pdf_text, expected_title, activity_name) if expected_title else False
        results.append(ValidationResult(
            criterion=rule_name,
            passed=title_match,
            points_awarded=points if title_match else 0,
            message="" if title_match else f"PDF title does not match expected: {expected_title}"
        ))
        
        if not title_match:
            logger.warning("Event driven 3: Title mismatch detected - failing all PDF validations")
            # Rule 1: Expert details present - FAIL
            rule_name, points = PDF_RULES[1]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="PDF title mismatch - all PDF validations failed for event_driven=3"
            ))
            # Rule 2: Objectives and learning align - FAIL
            rule_name, points = PDF_RULES[2]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="PDF title mismatch - all PDF validations failed for event_driven=3"
            ))
            return results
        
        logger.info("Event driven 3: Title match PASSED - proceeding to run all PDF validations")
        # Fall through to run remaining PDF validations (expert details, objectives/learning)
    
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
    
    # For non-event_driven=3 cases, do fuzzy title matching here
    if event_driven != 3:
        # Rule 0: PDF title matches metadata (7 points)
        rule_name, points = PDF_RULES[0]
        title_match = _fuzzy_match_pdf_title(pdf_text, expected_title, activity_name) if expected_title else False
        results.append(ValidationResult(
            criterion=rule_name,
            passed=title_match,
            points_awarded=points if title_match else 0,
            message="" if title_match else f"PDF title does not match expected: {expected_title}"
        ))
    
    # Rule 1: Expert details present (7 points)
    # Use heuristic check first, then AI result
    rule_name, points = PDF_RULES[1]
    expert_passed = validation_results.get("expert_details_present", False) or has_expert_keywords
    results.append(ValidationResult(
        criterion=rule_name,
        passed=expert_passed,
        points_awarded=points if expert_passed else 0,
        message="" if expert_passed else "Expert details not found in PDF"
    ))
    
    # Rule 2: Objectives and learning align (6 points)
    # SPECIAL CASE: If title doesn't match, this should probably fail too? 
    # Current logic relies on semantic check results
    rule_name, points = PDF_RULES[2]
    
    # Check both learning_match AND objectives_match from unified result
    learning_passed = validation_results.get("learning_match", False) or validation_results.get("objectives_match", False)
    
    # If title failed, this fails too (per user request for strictness)
    final_pass = learning_passed and title_match
    
    results.append(ValidationResult(
        criterion=rule_name,
        passed=final_pass,
        points_awarded=points if final_pass else 0,
        message="" if final_pass else ("Objectives/Learning outcomes not aligned" if title_match else "PDF title mismatch - objectives/learning validation failed")
    ))
    
    logger.debug(f"PDF validation complete. Reasoning: {validation_results.get('reasoning', 'N/A')}")
    
    return results

