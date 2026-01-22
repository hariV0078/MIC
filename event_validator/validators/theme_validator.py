"""Theme validation using hardcoded rules and Gemini."""
import logging
from typing import List, Optional
from datetime import datetime

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import THEME_RULES
from event_validator.validators.gemini_client import GeminiClient
from event_validator.utils.column_mapper import validate_level_duration_match, LEVEL_DEFINITIONS
from event_validator.utils.title_generator import (
    get_expected_title,
    format_title_validation_message,
    should_validate_against_canonical_title
)

logger = logging.getLogger(__name__)


def validate_theme_alignment(
    submission: EventSubmission,
    gemini_client: GeminiClient
) -> ValidationResult:
    """
    Check if title/objectives/learning align to theme.
    
    Uses event-driven title policy:
    - event_driven 1, 2, 4: Validates against canonical title
    - event_driven 3: Validates user-provided title against theme
    """
    rule_name, points = THEME_RULES[0]
    
    row_data = submission.row_data
    theme = row_data.get('Theme', '').strip()
    objectives = row_data.get('Objectives', '').strip()
    learning_outcomes = row_data.get('Learning Outcomes', '').strip()
    event_type = row_data.get('Event Type', '').strip()
    
    # Get event_driven and activity_name (event title) from original data
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = original_data.get('event_driven')
    
    # activity_name is the field that contains the event title
    # It's mapped to 'Title' in column_mapper, but get it from original data to be explicit
    activity_name = original_data.get('activity_name', '').strip()
    user_title = row_data.get('Title', '').strip() or activity_name  # Use activity_name if Title is empty
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    logger.debug(f"  Theme: {theme}")
    logger.debug(f"  Event Driven: {event_driven}")
    logger.debug(f"  Activity Name (Event Title): {activity_name[:100] if activity_name else 'N/A'}")
    logger.debug(f"  User Title: {user_title[:100] if user_title else 'N/A'}")
    logger.debug(f"  Objectives: {objectives[:100] if objectives else 'N/A'}")
    logger.debug(f"  Learning Outcomes: {learning_outcomes[:100] if learning_outcomes else 'N/A'}")
    
    if not theme:
        logger.warning(f"  FAIL: Theme missing")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Theme missing — cannot validate alignment"
        )
    
    # Get expected title based on event_driven policy
    # Use activity_name as the user_title since it's the primary event title field
    title_for_expected = activity_name or user_title
    expected_title = get_expected_title(
        event_driven=event_driven,
        user_title=title_for_expected,
        event_type=event_type,
        theme=theme,
        objectives=objectives,
        learning_outcomes=learning_outcomes
    )
    
    # Use activity_name (event title) for theme alignment check
    # activity_name is the primary field containing the event title
    event_title_for_check = activity_name or user_title or expected_title
    
    # Use Gemini/Groq for semantic alignment check (adaptive routing: prefers Groq for text tasks)
    logger.debug("  Calling API for theme alignment check (adaptive routing: prefers Groq for text)...")
    logger.debug(f"  Using event title for theme check: {event_title_for_check[:100] if event_title_for_check else 'N/A'}")
    aligned = gemini_client.check_theme_alignment(
        title=event_title_for_check,
        objectives=objectives,
        learning_outcomes=learning_outcomes,
        theme=theme,
        prefer_groq=True  # Prefer Groq for text tasks to preserve Gemini quota for vision
    )
    
    if aligned:
        logger.info(f"  PASS: Theme alignment confirmed | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        # Format audit-ready failure message
        # Use activity_name as the observed title since it's the primary event title field
        observed_title = activity_name or user_title
        failure_reason = "Content does not semantically align with declared theme"
        message = format_title_validation_message(
            event_driven=event_driven,
            expected_title=expected_title,
            observed_title=observed_title,
            reason=failure_reason
        )
        
        logger.warning(f"  FAIL: Theme alignment not confirmed | Points: 0")
        logger.debug(f"  Observed Title (activity_name): {observed_title}")
        logger.debug(f"  Theme: {theme}")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=message
        )


def validate_level_duration(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None
) -> ValidationResult:
    """Check if level matches duration."""
    rule_name, points = THEME_RULES[1]
    
    row_data = submission.row_data
    level = str(row_data.get('Level', '')).strip()
    duration = str(row_data.get('Duration', '')).strip()
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    logger.debug(f"  Level: {level}, Duration: {duration}")
    
    # Parse duration (e.g., "3h", "2 hours", "180 minutes")
    duration_hours = _parse_duration(duration)
    
    if not level or not duration_hours:
        logger.warning(f"  FAIL: Level or Duration missing/invalid | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Level or Duration missing/invalid. Level: {level}, Duration: {duration}"
        )
    
    try:
        level_int = int(level)
    except (ValueError, TypeError):
        logger.warning(f"  FAIL: Invalid level format | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Invalid level format: {level}"
        )
    
    # Use new level definitions
    if level_int not in LEVEL_DEFINITIONS:
        logger.warning(f"  FAIL: Invalid level | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Invalid level: {level}. Valid levels are 1-4."
        )
    
    # Validate level matches duration
    if validate_level_duration_match(level_int, duration_hours):
        logger.info(f"  PASS: Level {level} matches duration {duration_hours}h | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        definition = LEVEL_DEFINITIONS[level_int]
        min_hours, max_hours = definition["duration_range"]
        if max_hours == float('inf'):
            expected_range = f"{min_hours}+ hours"
        else:
            expected_range = f"{min_hours}-{max_hours} hours"
        
        logger.warning(f"  FAIL: Duration {duration_hours}h does not match Level {level} requirements ({expected_range}) | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Duration {duration_hours}h does not match Level {level} requirements ({expected_range})"
        )


def validate_participants_reported(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None
) -> ValidationResult:
    """Check if participants reported > 20."""
    rule_name, points = THEME_RULES[2]
    
    row_data = submission.row_data
    participants_str = str(row_data.get('Participants', '0')).strip()
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    
    try:
        participants = int(float(participants_str))
    except (ValueError, TypeError):
        participants = 0
    
    logger.debug(f"  Participants: {participants}")
    
    if participants > 20:
        logger.info(f"  PASS: {participants} participants reported (> 20) | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        logger.warning(f"  FAIL: {participants} participants reported (needs > 20) | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Participants reported: {participants} (needs > 20)"
        )


def validate_year_alignment(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None
) -> ValidationResult:
    """Check year alignment (financial vs academic)."""
    rule_name, points = THEME_RULES[3]
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    
    row_data = submission.row_data
    event_date_str = str(row_data.get('Event Date', '')).strip()
    year_type = str(row_data.get('Year Type', 'Financial')).strip()
    
    logger.debug(f"  Event Date: {event_date_str}, Year Type: {year_type}")
    
    if not event_date_str:
        logger.warning(f"  FAIL: Event Date missing | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Event Date missing"
        )
    
    # Parse event date
    event_date = _parse_date(event_date_str)
    if not event_date:
        logger.warning(f"  FAIL: Invalid event date format | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message=f"Invalid event date format: {event_date_str}"
        )
    
    event_year = event_date.year
    current_year = datetime.now().year
    logger.debug(f"  Event Year: {event_year}, Current Year: {current_year}")
    
    # Financial year: April to March (e.g., FY 2024 = April 2023 to March 2024)
    # Academic year: Typically July to June
    # For simplicity, check if year is within reasonable range
    if year_type.lower() == 'financial':
        # Financial year validation
        if event_date.month >= 4:
            financial_year = event_year
        else:
            financial_year = event_year - 1
        
        # Check if within current or previous financial year
        if abs(financial_year - current_year) <= 1:
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
                message=f"Financial year {financial_year} does not align with current year {current_year}"
            )
    else:
        # Academic year validation (simplified)
        if abs(event_year - current_year) <= 1:
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
                message=f"Academic year {event_year} does not align with current year {current_year}"
            )


def validate_theme(submission: EventSubmission, gemini_client: GeminiClient) -> List[ValidationResult]:
    """Run all theme validations."""
    results = []
    
    results.append(validate_theme_alignment(submission, gemini_client))
    results.append(validate_level_duration(submission))
    results.append(validate_participants_reported(submission))
    # Year alignment validation is DISABLED per user request
    # User provides dates in from_date, to_date, and academic_year - no need to validate against current date
    # results.append(validate_year_alignment(submission))
    
    return results


def _parse_duration(duration_str: str) -> Optional[float]:
    """Parse duration string to hours."""
    duration_str = duration_str.lower().strip()
    
    # Remove common words
    duration_str = duration_str.replace('hours', '').replace('hour', '').replace('hrs', '').replace('hr', '')
    duration_str = duration_str.replace('minutes', '').replace('minute', '').replace('mins', '').replace('min', '')
    duration_str = duration_str.replace('h', '').replace('m', '')
    
    try:
        # Try to extract number
        import re
        numbers = re.findall(r'\d+\.?\d*', duration_str)
        if numbers:
            value = float(numbers[0])
            
            # If original had 'min' or 'minutes', convert to hours
            if 'min' in duration_str.lower() or 'm' in duration_str.lower():
                value = value / 60.0
            
            return value
    except (ValueError, TypeError):
        pass
    
    return None


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to datetime object."""
    date_formats = [
        '%Y-%m-%d',
        '%d-%m-%Y',
        '%m/%d/%Y',
        '%d/%m/%Y',
        '%Y/%m/%d',
        '%d %B %Y',
        '%B %d, %Y',
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None

