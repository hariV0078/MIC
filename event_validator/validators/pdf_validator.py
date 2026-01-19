"""PDF validation using hardcoded rules and Gemini."""
import logging
from typing import List, Optional

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import PDF_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


def validate_pdf_title_match(
    submission: EventSubmission,
    gemini_client: GeminiClient
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
    consistency = gemini_client.check_pdf_consistency(
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
    gemini_client: Optional[GeminiClient] = None
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
    gemini_client: GeminiClient
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
    consistency = gemini_client.check_pdf_consistency(
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
    gemini_client: GeminiClient
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
    consistency = gemini_client.check_pdf_consistency(
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
    gemini_client: GeminiClient
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
    consistency = gemini_client.check_pdf_consistency(
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
            message=f"PDF participant information does not match expected (needs 20+ participants)"
        )


def validate_pdf(submission: EventSubmission, gemini_client: GeminiClient) -> List[ValidationResult]:
    """Run all PDF validations."""
    results = []
    
    results.append(validate_pdf_title_match(submission, gemini_client))
    results.append(validate_expert_details(submission, gemini_client))
    results.append(validate_learning_outcomes_align(submission, gemini_client))
    results.append(validate_objectives_match(submission, gemini_client))
    results.append(validate_participant_info_match(submission, gemini_client))
    
    return results

