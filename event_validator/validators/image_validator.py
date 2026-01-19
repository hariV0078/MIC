"""Image validation using hardcoded rules and Gemini."""
import logging
from typing import List, Optional
from pathlib import Path

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import IMAGE_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


def validate_geotag_present(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None
) -> ValidationResult:
    """Check if geotag is present in images."""
    rule_name, points = IMAGE_RULES[0]
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    
    if not submission.images:
        logger.warning(f"  FAIL: No images provided | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    # Check if any image has geotag
    has_geotag = any(img.has_geotag for img in submission.images)
    logger.debug(f"  Images checked: {len(submission.images)}, Geotag found: {has_geotag}")
    
    if has_geotag:
        logger.info(f"  PASS: Geotag found in images | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message=""
        )
    else:
        logger.warning(f"  FAIL: No geotag found in any image | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No geotag found in any image"
        )


def validate_banner_poster_visible(
    submission: EventSubmission,
    gemini_client: GeminiClient
) -> ValidationResult:
    """Check if banner/poster is visible in images."""
    rule_name, points = IMAGE_RULES[1]
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    # Use Gemini to analyze images for banner/poster
    # For now, check first image (can be extended to check all)
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    row_data = submission.row_data
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    
    analysis = gemini_client.analyze_image(
        image_path=image_path,
        event_title=event_title,
        event_theme=event_theme
    )
    
    if analysis.get("has_banner", False):
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
            message="Banner or poster not visible in images"
        )


def validate_real_activity_scene(
    submission: EventSubmission,
    gemini_client: GeminiClient
) -> ValidationResult:
    """Check if event scene is real activity."""
    rule_name, points = IMAGE_RULES[2]
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    # Use Gemini to analyze if image shows real event
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    row_data = submission.row_data
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    
    analysis = gemini_client.analyze_image(
        image_path=image_path,
        event_title=event_title,
        event_theme=event_theme
    )
    
    if analysis.get("is_real_event", False):
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
            message="Image does not depict a real event activity"
        )


def validate_event_mode_matches(
    submission: EventSubmission,
    gemini_client: GeminiClient
) -> ValidationResult:
    """Check if event mode matches (online/offline)."""
    rule_name, points = IMAGE_RULES[3]
    
    row_data = submission.row_data
    event_mode = str(row_data.get('Event Mode', '')).strip().lower()
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    # Use Gemini to analyze if mode matches
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    
    analysis = gemini_client.analyze_image(
        image_path=image_path,
        event_mode=event_mode,
        event_title=event_title,
        event_theme=event_theme
    )
    
    if analysis.get("mode_matches", False):
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
            message=f"Event mode in image does not match specified mode: {event_mode}"
        )


def validate_20_plus_participants_visible(
    submission: EventSubmission,
    gemini_client: GeminiClient
) -> ValidationResult:
    """Check if 20+ participants are visible in images."""
    rule_name, points = IMAGE_RULES[4]
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    # Use Gemini to analyze participant count
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    row_data = submission.row_data
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    
    analysis = gemini_client.analyze_image(
        image_path=image_path,
        event_title=event_title,
        event_theme=event_theme
    )
    
    if analysis.get("has_20_plus_participants", False):
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
            message="20+ participants not visible in images"
        )


def validate_images(submission: EventSubmission, gemini_client: GeminiClient) -> List[ValidationResult]:
    """Run all image validations."""
    results = []
    
    # Geotag validation is DISABLED per user request
    # results.append(validate_geotag_present(submission))
    
    results.append(validate_banner_poster_visible(submission, gemini_client))
    results.append(validate_real_activity_scene(submission, gemini_client))
    results.append(validate_event_mode_matches(submission, gemini_client))
    results.append(validate_20_plus_participants_visible(submission, gemini_client))
    
    return results

