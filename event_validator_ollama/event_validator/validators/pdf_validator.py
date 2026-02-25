"""PDF validation using hardcoded rules and Gemini."""
import logging
import re
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
    """Check if PDF title matches metadata semantically."""
    rule_name, points = PDF_RULES[0]
    
    row_data = submission.row_data
    expected_title = str(row_data.get('Title', '')).strip()
    
    if not submission.pdf_data or not submission.pdf_data.text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
            message="PDF text not extracted"
        )
    
    # Use LLM for semantic title matching
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
            points_awarded=float(points),
            message="Title matched via semantic analysis"
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
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
            points_awarded=0.0,
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
            points_awarded=float(points),
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
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
            points_awarded=0.0,
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
            points_awarded=float(points),
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
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
            points_awarded=0.0,
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
            points_awarded=float(points),
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
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
            points_awarded=0.0,
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
            points_awarded=float(points),
            message=""
        )
    else:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
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
                points_awarded=float(points),
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
                points_awarded=0.0,
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
    def _get_event_driven_id(data):
        raw = data.get('event_driven') or data.get('Event Driven')
        if raw is None: return None
        try: return int(float(str(raw).strip()))
        except: return None
        
    # Get original row data (if stored on submission) for event_driven/activity_name lookups
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = _get_event_driven_id(original_data)
    
    # Get activity_name from original row data for fuzzy matching
    activity_name = str(original_data.get('activity_name', '')).strip()
    
    # FLOW 2: Relevance Gate (For Types 1, 2, 4)
    if event_driven in (1, 2, 4):
        logger.info(f"Executing Flow 2: PDF Relevance Check for '{activity_name}'")
        is_relevant = ollama_client.check_pdf_relevance(pdf_text, activity_name)
        
        if not is_relevant:
            logger.warning(f"FLOW 2 FAIL: PDF content not relevant to activity '{activity_name}'. Activating Kill Switch.")
            submission.kill_switch = True
            for rule_name, _ in PDF_RULES:
                results.append(ValidationResult(
                    criterion=rule_name,
                    passed=False,
                    points_awarded=0.0,
                    message=f"REJECTED: PDF content irrelevant to activity '{activity_name}' (Flow 2 Fail)"
                ))
            return results
    
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
                    points_awarded=0.0,
                    message="Theme alignment failed - This submission requires strict theme matching (Event Driven 3)."
                ))
            return results
        
        logger.info("Event driven 3: Theme alignment PASSED - proceeding to title check")
        
        # Step 2: PDF title must match semantically
        rule_name, points = PDF_RULES[0]
        consistency = ollama_client.check_pdf_consistency(
            pdf_text=pdf_text,
            expected_title=expected_title,
            expected_objectives=None,
            expected_learning_outcomes=None,
            expected_participants=None
        )
        title_match = consistency.get("title_match", False)
        results.append(ValidationResult(
            criterion=rule_name,
            passed=title_match,
            points_awarded=float(points) if title_match else 0.0,
            message="" if title_match else f"PDF title mismatch - semantic match not found for: {expected_title} (Event Driven 3)."
        ))
        
        if not title_match:
            logger.warning("Event driven 3: Title mismatch detected - failing all PDF validations")
            # Rule 1: Expert details present - FAIL
            rule_name, points = PDF_RULES[1]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="PDF title mismatch - skipping expert details check (Event Driven 3)."
            ))
            # Rule 2: Objectives and learning align - FAIL
            rule_name, points = PDF_RULES[2]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="PDF title mismatch - skipping objectives/learning check (Event Driven 3)."
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
    
    # For non-event_driven=3 cases, do semantic title matching here
    if event_driven != 3:
        # Rule 0: PDF title matches metadata (7 points)
        rule_name, points = PDF_RULES[0]
        # Use existing unified result for title match
        title_match = validation_results.get("title_match", False)
        results.append(ValidationResult(
            criterion=rule_name,
            passed=title_match,
            points_awarded=float(points) if title_match else 0.0,
            message="" if title_match else f"PDF title does not match expected title: {expected_title}"
        ))
        
        # KILL SWITCH: If title doesn't match for types 1,2,4 → zero ALL remaining scores
        if not title_match and event_driven in (1, 2, 4):
            logger.warning(f"PDF Title mismatch for event_driven={event_driven}. Activating Kill Switch.")
            submission.kill_switch = True
            # Zero out expert details (Rule 1)
            rule_name, points = PDF_RULES[1]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="Kill switch: PDF title mismatch — expert score zeroed"
            ))
            # Zero out objectives/learning (Rule 2)
            rule_name, points = PDF_RULES[2]
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="Kill switch: PDF title mismatch — objectives/learning score zeroed"
            ))
            logger.info("Kill switch active: All PDF scores zeroed, theme+image will be zeroed by runner.")
            return results
    
    # Rule 1: Expert details present (7 points)
    # Use heuristic check first, then AI result
    rule_name, points = PDF_RULES[1]
    expert_passed = validation_results.get("expert_details_present", False) or has_expert_keywords
    
    # DEPENDENCY: If title failed, expert score MUST be zero (as per user requirement)
    final_expert_pass = expert_passed and title_match
    
    results.append(ValidationResult(
        criterion=rule_name,
        passed=final_expert_pass,
        points_awarded=float(points) if final_expert_pass else 0.0,
        message="" if final_expert_pass else ("Expert/Speaker details not found in PDF" if title_match else "Kill switch: PDF title mismatch — expert score zeroed")
    ))
    
    # Rule 2: Objectives and learning align (6 points)
    rule_name, points = PDF_RULES[2]
    
    # Check both learning_match AND objectives_match from unified result
    learning_passed = validation_results.get("learning_match", False) or validation_results.get("objectives_match", False)
    
    # DEPENDENCY: If title failed, objectives score MUST be zero
    final_learning_pass = learning_passed and title_match
    
    results.append(ValidationResult(
        criterion=rule_name,
        passed=final_learning_pass,
        points_awarded=float(points) if final_learning_pass else 0.0,
        message="" if final_learning_pass else ("Objectives/Learning outcomes not clearly stated/aligned in PDF" if title_match else "PDF title mismatch - objectives/learning validation failed")
    ))
    
    logger.debug(f"PDF validation complete. Reasoning: {validation_results.get('reasoning', 'N/A')}")
    
    return results

