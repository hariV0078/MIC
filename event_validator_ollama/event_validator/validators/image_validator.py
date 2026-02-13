"""Image validation using hardcoded rules and Ollama."""
import logging
from typing import List, Optional
from pathlib import Path

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import IMAGE_RULES
from event_validator.validators.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def validate_geotag_present(
    submission: EventSubmission,
    text_analysis: Optional[dict] = None
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
    
    # If metadata check failed, try visual geotag check using OCR text
    if not has_geotag and text_analysis and text_analysis.get("has_visual_geotag", False):
        logger.info(f"  PASS: Visual geotag/overlay detected in image | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message="Visual geotag overlay detected"
        )

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
    analysis: Optional[dict] = None,
    text_analysis: Optional[dict] = None
) -> ValidationResult:
    """Check if banner/poster is visible in images.
    
    Uses two methods:
    1. Vision model banner detection (has_banner)
    2. Text extraction from image - checks for event details (date, time, event type, etc.)
    Passes if EITHER method succeeds.
    """
    rule_name, points = IMAGE_RULES[1]
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    if analysis is None:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Image analysis not provided"
        )
    
    # Method 1: Original banner detection from vision model
    has_banner = analysis.get("has_banner", False)
    
    # Method 2: Extract text from image and check for event details
    has_event_details = False
    if text_analysis:
        has_event_details = text_analysis.get("has_event_details", False)
        if has_event_details:
            details = text_analysis.get("event_details_found", [])
            logger.info(f"Banner check: event details found in image text: {details}")
    
    if has_banner or has_event_details:
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
    analysis: Optional[dict] = None
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
    
    if analysis is None:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Image analysis not provided"
        )
    
    # Pass if real event detected OR 15+ participants visible (participants imply real event)
    if analysis.get("is_real_event", False) or analysis.get("has_15_plus_participants", False):
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





def validate_15_plus_participants_visible(
    submission: EventSubmission,
    analysis: Optional[dict] = None
) -> ValidationResult:
    """Check if 15+ participants are visible in images."""
    rule_name, points = IMAGE_RULES[3]
    
    if not submission.images:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="No images provided"
        )
    
    if analysis is None:
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Image analysis not provided"
        )
    
    if analysis.get("has_15_plus_participants", False):
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
            message="15+ participants not visible in images"
        )


def validate_images(submission: EventSubmission, ollama_client: OllamaClient) -> List[ValidationResult]:
    """Run all image validations."""
    results = []
    
    # Geotag validation is ENABLED
    # Geotag validation will be run after text extraction
    
    if not submission.images:
        # Return failed results for all validations if no images
        results.append(validate_geotag_present(submission))
        results.append(validate_banner_poster_visible(submission, None))
        results.append(validate_real_activity_scene(submission, None))
        results.append(validate_15_plus_participants_visible(submission, None))
        return results
    
    # OPTIMIZATION: Call analyze_image() ONCE and reuse results for all validations
    # This reduces 4 API calls to 1 API call per image (4x faster!)
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    row_data = submission.row_data
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    event_mode = str(row_data.get('Event Mode', '')).strip().lower()
    
    logger.info(f"Analyzing image once for all validations: {image_path.name}")
    analysis = ollama_client.analyze_image(
        image_path=image_path,
        event_mode=event_mode,
        event_title=event_title,
        event_theme=event_theme
    )
    
    # Reuse the same analysis result for all validation functions
    # Extract text from image for banner and geotag checks
    logger.info(f"Extracting text from image for validations: {image_path.name}")
    text_analysis = ollama_client.extract_text_from_image(str(image_path))
    
    # Run validations
    results.append(validate_geotag_present(submission, text_analysis))
    
    results.append(validate_banner_poster_visible(
        submission, analysis,
        text_analysis=text_analysis
    ))
    results.append(validate_real_activity_scene(submission, analysis))
    results.append(validate_15_plus_participants_visible(submission, analysis))
    
    return results

