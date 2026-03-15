"""PDF validation using unified Gemini checks with Ollama-equivalent criteria flow."""
import logging
import hashlib
from typing import List

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

def _is_mic_event(submission: EventSubmission) -> bool:
    """Check if this is a MIC event - automatically accept PDF validation."""
    row_data = submission.row_data
    original_data = getattr(submission, '_original_row_data', row_data)

    event_type = str(row_data.get('Event Type', '')).strip().upper()
    theme = str(row_data.get('Theme', '')).strip().upper()
    title = str(row_data.get('Title', '')).strip().upper()
    activity_name = str(original_data.get('activity_name', '')).strip().upper()

    mic_indicators = ['MIC', 'MIC-IIC', 'MIC IIC']
    for indicator in mic_indicators:
        if (
            indicator in event_type
            or indicator in theme
            or indicator in title
            or indicator in activity_name
        ):
            return True

    return False


def validate_pdf(
    submission: EventSubmission, 
    gemini_client: GeminiClient
) -> List[ValidationResult]:
    """
    Run all PDF validations using a single unified API call.

    Special cases:
    - MIC events auto-pass all PDF rules.
    - event_driven 1/2/4 run Flow 2 relevance gate.
    - event_driven 3 runs strict theme->title->PDF sequencing.
    """
    results = []

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
    
    # Get extracted text
    pdf_text = ""
    if submission.pdf_data:
        pdf_text = submission.pdf_data.text or ""
    
    # Get expected values
    row_data = submission.row_data
    expected_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    expected_objectives = row_data.get('Objectives', '')
    expected_outcomes = row_data.get('Learning Outcomes', '')
    theme = row_data.get('Theme', '')
    
    # Extract expected participants
    expected_participants = None
    try:
        participants_str = str(row_data.get('Participants', '0')).strip()
        expected_participants = int(float(participants_str))
    except (ValueError, TypeError):
        pass
    
    # activity_name for relevance check
    original_data = getattr(submission, '_original_row_data', row_data)
    activity_name = original_data.get('activity_name', expected_title)
    
    def _get_event_driven_id(data):
        raw = data.get('event_driven') or data.get('Event Driven')
        if raw is None: return None
        try: return int(float(str(raw).strip()))
        except: return None
        
    event_driven = _get_event_driven_id(original_data)

    if not pdf_text:
        for rule_name, _ in PDF_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="No PDF text extracted"
            ))
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

    if event_driven == 3:
        logger.info("Event driven 3: running strict validation flow (theme -> title -> PDF checks)")
        theme_aligned = gemini_client.check_theme_alignment(
            title=activity_name or expected_title,
            objectives=expected_objectives,
            learning_outcomes=expected_outcomes,
            theme=theme,
            prefer_groq=False,
        )

        if not theme_aligned:
            logger.warning("Event driven 3: theme alignment failed - failing all PDF validations")
            for rule_name, _ in PDF_RULES:
                results.append(ValidationResult(
                    criterion=rule_name,
                    passed=False,
                    points_awarded=0.0,
                    message="Theme alignment failed - strict event driven 3 PDF flow"
                ))
            return results

        title_rule, title_points = PDF_RULES[0]
        title_consistency = gemini_client.check_pdf_consistency(
            pdf_text=pdf_text,
            expected_title=expected_title,
            expected_objectives=None,
            expected_learning_outcomes=None,
            expected_participants=None,
        )
        title_match = title_consistency.get("title_match", False)
        results.append(ValidationResult(
            criterion=title_rule,
            passed=title_match,
            points_awarded=float(title_points) if title_match else 0.0,
            message="" if title_match else f"PDF title mismatch for event driven 3: {expected_title}"
        ))

        if not title_match:
            for rule_name, _ in PDF_RULES[1:]:
                results.append(ValidationResult(
                    criterion=rule_name,
                    passed=False,
                    points_awarded=0.0,
                    message="PDF title mismatch - skipping remaining PDF checks (Event Driven 3)"
                ))
            return results

    pdf_hash = hashlib.sha256(pdf_text.encode('utf-8')).hexdigest()[:16]

    llm_results = gemini_client.validate_pdf_comprehensive(
        pdf_text=pdf_text,
        expected_title=expected_title,
        expected_objectives=expected_objectives,
        expected_learning_outcomes=expected_outcomes,
        expected_participants=expected_participants,
        pdf_hash=pdf_hash
    )

    # Rule 1: Title Match
    title_rule, title_points = PDF_RULES[0]
    if event_driven != 3:
        title_match = llm_results.get("title_match", False)
        results.append(ValidationResult(
            criterion=title_rule,
            passed=title_match,
            points_awarded=float(title_points) if title_match else 0.0,
            message="" if title_match else f"PDF title does not match expected title: {expected_title}"
        ))

    if event_driven in (1, 2, 4) and not title_match:
        logger.warning(f"PDF Title mismatch for event_driven={event_driven}. Activating Kill Switch.")
        submission.kill_switch = True
        for rule_name, _ in PDF_RULES[1:]:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="Kill switch: PDF title mismatch — score zeroed"
            ))
        logger.info("Kill switch active: All PDF scores zeroed, theme+image will be zeroed by runner.")
        return results

    # Rule 2: Expert details
    rule_name, points = PDF_RULES[1]
    expert_passed = llm_results.get("expert_details_present", False)
    final_expert_pass = expert_passed and title_match
    results.append(ValidationResult(
        criterion=rule_name,
        passed=final_expert_pass,
        points_awarded=float(points) if final_expert_pass else 0.0,
        message="" if final_expert_pass else ("Expert/Speaker details not found in PDF" if title_match else "Kill switch: PDF title mismatch — expert score zeroed")
    ))

    # Rule 3: Objectives and learning align
    rule_name, points = PDF_RULES[2]
    learning_passed = llm_results.get("learning_outcomes_align", False) or llm_results.get("objectives_match", False)
    final_learning_pass = learning_passed and title_match
    results.append(ValidationResult(
        criterion=rule_name,
        passed=final_learning_pass,
        points_awarded=float(points) if final_learning_pass else 0.0,
        message="" if final_learning_pass else ("Objectives/Learning outcomes not clearly stated/aligned in PDF" if title_match else "Kill switch: PDF title mismatch — score zeroed")
    ))

    return results
