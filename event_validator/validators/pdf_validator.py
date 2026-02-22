"""PDF validation using simple string matching first, then Gemini."""
import logging
from typing import List, Optional, Dict, Any

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Re-use the clean_title logic from client for consistency

def validate_pdf_title(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None,
    pdf_text: str = ""
) -> ValidationResult:
    """Check if PDF title matches event title semantically."""
    rule_name, points = PDF_RULES[0]
    
    row_data = submission.row_data
    expected_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    
    if not pdf_text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No PDF text extracted"
        )
        
    if not gemini_client:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="LLM not available for semantic title check"
        )
        
    consistency = gemini_client.check_pdf_consistency(
        pdf_text=pdf_text,
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
            message="Title matched via semantic analysis"
        )
        
    return ValidationResult(
        criterion=rule_name,
        passed=False,
        points_awarded=0,
        message=f"PDF title does not match '{expected_title}'"
    )


def validate_pdf(
    submission: EventSubmission, 
    gemini_client: GeminiClient
) -> List[ValidationResult]:
    """
    Run all PDF content validations using a single comprehensive LLM call.
    Includes fallback to string matching for title to save tokens.
    
    REDEFINED FLOW (Types 1, 2, 4):
    Flow 2: Check if activity name is relevant to PDF content.
    If relevance fails, mark 0 for all PDF and signal kill switch.
    """
    results = []
    
    # Get extracted text
    pdf_text = ""
    if submission.pdf_data:
        pdf_text = submission.pdf_data.text or ""
    
    # Get expected values
    row_data = submission.row_data
    expected_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    expected_objectives = row_data.get('Objective', '')
    expected_outcomes = row_data.get('Learning Outcomes', '')
    theme = row_data.get('Theme', '')
    
    # activity_name for relevance check
    original_data = getattr(submission, '_original_row_data', row_data)
    activity_name = original_data.get('activity_name', expected_title)
    event_driven = original_data.get('event_driven')

    if not pdf_text:
        # Fail all if no text
        for rule_name, _ in PDF_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="No PDF text extracted"
            ))
        # No text = Relevance failed
        if event_driven in (1, 2, 4):
            submission.kill_switch = True
        return results

    # FLOW 2: Relevance Gate (For Types 1, 2, 4)
    if event_driven in (1, 2, 4):
        logger.info(f"Executing Flow 2: PDF Relevance Check for '{activity_name}'")
        is_relevant = gemini_client.check_pdf_relevance(pdf_text, activity_name)
        
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

    # LLM Call (Comprehensive)
    # We pass the pdf_hash to enable caching of this expensive call
    pdf_hash = None
    try:
        import hashlib
        pdf_hash = hashlib.md5(pdf_text.encode('utf-8')).hexdigest()
    except Exception:
        pass

    llm_results = gemini_client.validate_pdf_comprehensive(
        pdf_text=pdf_text,
        expected_title=expected_title,
        expected_objectives=expected_objectives,
        expected_learning_outcomes=expected_outcomes,
        expected_participants=15, # We verify 15+ participants
        pdf_hash=pdf_hash
    )
    
    # 3. Construct Results
    
    # Rule 1: Title Match (Purely Semantic)
    title_rule, title_points = PDF_RULES[0]
    final_title_pass = llm_results.get("title_match", False)
    results.append(ValidationResult(
        criterion=title_rule,
        passed=final_title_pass,
        points_awarded=title_points if final_title_pass else 0,
        message="" if final_title_pass else f"Title mismatch. Expected similar to: {expected_title}"
    ))
    
    # Rule 2: Expert Details
    rule_name, points = PDF_RULES[1]
    passed = llm_results.get("expert_details_present", False)
    results.append(ValidationResult(
        criterion=rule_name,
        passed=passed,
        points_awarded=points if passed else 0,
        message="" if passed else "Expert/Speaker details missing"
    ))
    
    # Rule 3: Learning Outcomes
    rule_name, points = PDF_RULES[2]
    passed = llm_results.get("learning_outcomes_align", False)
    results.append(ValidationResult(
        criterion=rule_name,
        passed=passed,
        points_awarded=points if passed else 0,
        message="" if passed else "Learning outcomes do not align"
    ))
    
    # Rule 4: Objectives
    rule_name, points = PDF_RULES[3]
    passed = llm_results.get("objectives_match", False)
    results.append(ValidationResult(
        criterion=rule_name,
        passed=passed,
        points_awarded=points if passed else 0,
        message="" if passed else "Objectives do not match"
    ))
    
    # Rule 5: Participants Count (PDF)
    rule_name, points = PDF_RULES[4]
    passed = llm_results.get("participants_valid", False)
    results.append(ValidationResult(
        criterion=rule_name,
        passed=passed,
        points_awarded=points if passed else 0,
        message="" if passed else "Participant count < 15 or missing in PDF"
    ))
    
    return results
