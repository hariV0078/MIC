"""PDF validation using simple string matching first, then Gemini."""
import logging
from typing import List, Optional, Dict, Any

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Re-use the clean_title logic from client for consistency
def _clean_title(title: str, theme: str = "") -> str:
    import re
    t = title.lower().strip()
    th = theme.lower().strip()
    
    # Normalize
    t = t.replace("&", "and")
    th = th.replace("&", "and")
    
    # Remove theme from title if present
    if th and th in t:
        t = re.sub(re.escape(th), "", t).strip()
    
    # Remove buzzwords
    buzzwords = [
        "entrepreneurship", "entrepreneur", "startup", "start-up", 
        "innovation", "design thinking", "workshop on", "session on", 
        "seminar on", "opportunities in", "guest lecture on", "field of", "opportunities"
    ]
    for bw in buzzwords:
        t = t.replace(bw, "")
    
    # Remove punctuation
    t = re.sub(r"^[\W_]+|[\W_]+$", "", t).strip()
    return t

def validate_pdf_title(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None,
    pdf_text: str = ""
) -> ValidationResult:
    """Check if PDF title matches event title."""
    rule_name, points = PDF_RULES[0]
    
    row_data = submission.row_data
    expected_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    theme = row_data.get('Theme', '')
    
    if not pdf_text:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No PDF text extracted"
        )
    
    # STRATEGY 1: Simple String Matching (Fast & Cheap)
    cleaned_pdf_text = pdf_text[:1000].lower() # Check first 1000 chars
    cleaned_expected = _clean_title(expected_title, theme)
    
    # Direct match of cleaned title
    if cleaned_expected and len(cleaned_expected) > 4 and cleaned_expected in cleaned_pdf_text:
        logger.info(f"PDF Title Match: Found '{cleaned_expected}' in PDF text (String Match)")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message="Title matched via string comparison"
        )
        
    # STRATEGY 2: LLM Validation (if string match fails)
    if not gemini_client:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Title not found in PDF (String match failed, no LLM available)"
        )
        
    # Note: We rely on the comprehensive check result if available, 
    # but for this specific function we might need to query if not already cached.
    # Ideally, we should pass the comprehensive result to these functions to avoid re-querying.
    # For now, we'll assume validate_pdf_content orchestrates this or we accept a re-query (cached).
    
    # We will let validate_pdf_content handle the LLM part if simple match fails
    # But since this function needs to return a result, we'll check consistency here
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


def validate_pdf_content(
    submission: EventSubmission, 
    gemini_client: GeminiClient
) -> List[ValidationResult]:
    """
    Run all PDF content validations using a single comprehensive LLM call.
    Includes fallback to string matching for title to save tokens.
    """
    results = []
    
    # Get extracted text
    pdf_text = ""
    if submission.pdfs:
        pdf_text = submission.pdfs[0].extracted_text or ""
    
    if not pdf_text:
        # Fail all if no text
        for rule_name, _ in PDF_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="No PDF text extracted"
            ))
        return results

    # Get expected values
    row_data = submission.row_data
    expected_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    expected_objectives = row_data.get('Objective', '')
    expected_outcomes = row_data.get('Learning Outcomes', '') # Fix key name if needed
    theme = row_data.get('Theme', '')
    
    # 1. OPTIMIZATION: Try String Match for Title FIRST
    title_rule, title_points = PDF_RULES[0]
    title_passed = False
    
    cleaned_pdf_head = pdf_text[:1000].lower()
    cleaned_expected = _clean_title(expected_title, theme)
    
    if cleaned_expected and len(cleaned_expected) > 4 and cleaned_expected in cleaned_pdf_head:
        title_passed = True
        logger.info(f"PDF Title Pre-check: Passed via string match ('{cleaned_expected}')")
        
    # 2. LLM Call (Comprehensive)
    # We pass the pdf_hash to enable caching of this expensive call
    pdf_hash = None
    if submission.pdfs and submission.pdfs[0].path:
        try:
            import hashlib
            with open(submission.pdfs[0].path, 'rb') as f:
                pdf_hash = hashlib.md5(f.read()).hexdigest()
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
    
    # Rule 1: Title Match (Use String match OR LLM result)
    final_title_pass = title_passed or llm_results.get("title_match", False)
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
