"""Image validation using hardcoded rules and Gemini."""
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import IMAGE_RULES
from event_validator.validators.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


def validate_geotag_present(
    submission: EventSubmission,
    gemini_client: Optional[GeminiClient] = None,
    text_analysis: Optional[dict] = None
) -> ValidationResult:
    """
    Check if geotag is present in images.
    Fallback: If no EXIF geotag, check 'text_analysis' for visual geotag indicators (e.g. GPS text overlay).
    """
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
    
    # Strat 1: EXIF Metadata Check
    has_geotag = any(img.has_geotag for img in submission.images)
    logger.debug(f"  Images checked: {len(submission.images)}, EXIF Geotag found: {has_geotag}")
    
    # Strat 2: Visual Geotag Fallback (OCR)
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
        # Debugging: Why did visual check fail?
        if text_analysis and "extracted_text" in text_analysis:
            preview = text_analysis["extracted_text"][:200].replace("\n", " ")
            logger.debug(f"  Visual Geotag Failed. OCR extracted: '{preview}...'")
            
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
    """Check if banner/poster is visible in images."""
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
    analysis: Optional[dict] = None
) -> ValidationResult:
    """Check if event mode matches (online/offline)."""
    rule_name, points = IMAGE_RULES[3]
    
    row_data = submission.row_data
    event_mode = str(row_data.get('Event Mode', '')).strip().lower()
    
    # Get event_driven for special handling
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = original_data.get('event_driven')
    try:
        event_driven = int(event_driven) if event_driven is not None else None
    except (ValueError, TypeError):
        event_driven = None
    
    # SPECIAL CASE: Event driven 2 is only online mode - give full score
    if event_driven == 2:
        logger.info(f"Event driven 2 detected - automatically passing event mode validation (online mode only)")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=points,
            message="Event driven 2 - online mode only (auto-passed)"
        )
    
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
    
    if analysis.get("mode_match", False) or analysis.get("mode_matches", False):
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


def validate_15_plus_participants_visible(
    submission: EventSubmission,
    analysis: Optional[dict] = None
) -> ValidationResult:
    """Check if 15+ participants are visible in images."""
    rule_name, points = IMAGE_RULES[4]
    
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

def validate_images(submission: EventSubmission, gemini_client: GeminiClient) -> List[ValidationResult]:
    """
    Run all image validations.
    
    REDEFINED FLOW:
    If kill_switch is active (from Flow 2 PDF failure), skip analysis and award 0 points.
    """
    results = []
    
    # KILL SWITCH: For Types 1, 2, 4 if Flow 2 failed
    if getattr(submission, 'kill_switch', False):
        logger.warning("Kill Switch is active (Flow 2 Fail). Skipping image analysis and awarding 0 points.")
        for rule_name, points in IMAGE_RULES:
            results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0.0,
                message="REJECTED: Kill switch active due to PDF relevance failure (Flow 2)"
            ))
        return results
    
    if not submission.images:
        # Return failed results for all validations if no images
        # Still run geotag check (will fail)
        results.append(validate_geotag_present(submission, gemini_client, None))
        results.append(validate_banner_poster_visible(submission, None))
        results.append(validate_real_activity_scene(submission, None))
        results.append(validate_event_mode_matches(submission, None))
        results.append(validate_15_plus_participants_visible(submission, None))
        return results
    
    # 1. GEOTAG LOOP: Check first few images for geotag if needed
    # First check EXIF (fastest)
    has_exif_geotag = any(img.has_geotag for img in submission.images)
    
    final_text_analysis = {}
    
    # Loop for visual geotag only if EXIF is missing
    if not has_exif_geotag:
        logger.info("No EXIF geotag found. Scanning first 3 images for visual geotag...")
        # OPTIMIZATION: Limit scan to first 3 images to avoid excessive API calls
        for i, img in enumerate(submission.images[:3]):
            img_path = img.path
            if not isinstance(img_path, Path):
                img_path = Path(img_path)
                
            logger.info(f"Scanning image {i+1}/{min(len(submission.images), 3)} for text: {img_path.name}")
            text_result = gemini_client.extract_text_from_image(img_path)
            
            # If we find a visual geotag, stop and use this result
            if text_result.get("has_visual_geotag", False):
                logger.info(f"Visual geotag found in image {i+1}!")
                final_text_analysis = text_result
                break
            
            # Keep the result of the first image as fallback/default if nothing better found
            if i == 0:
                final_text_analysis = text_result
    else:
        # If EXIF found, we still need text analysis for banner/poster check
        # Just use the first image for efficiency
        logger.info("EXIF geotag found. Using first image for text analysis.")
        img_path = submission.images[0].path
        if not isinstance(img_path, Path):
            img_path = Path(img_path)
        final_text_analysis = gemini_client.extract_text_from_image(img_path)
    
    
    # 2. IMAGE ANALYSIS: Use First Image
    # Call analyze_image()
    # Use the first image for detailed analysis (usually valid for validation)
    image_path = submission.images[0].path
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    
    # Get event context for better analysis
    row_data = submission.row_data
    event_title = row_data.get('Title', '') or row_data.get('activity_name', '')
    event_theme = row_data.get('Theme', '')
    event_mode = str(row_data.get('Event Mode', '')).strip().lower()
    
    logger.info(f"Analyzing primary image: {image_path.name}")
    analysis = gemini_client.analyze_image(
        image_path=image_path,
        event_mode=event_mode,
        event_title=event_title,
        event_theme=event_theme
    )
    
    # Log successful extraction for debugging
    if final_text_analysis.get("extracted_text"):
        logger.debug(f"OCR extracted text (first 100 chars): {final_text_analysis.get('extracted_text')[:100]}...")
    
    # Pass text_analysis to geotag validator for OCR fallback
    results.append(validate_geotag_present(submission, gemini_client, final_text_analysis))
    
    # Reuse the same analysis result for remaining validation functions
    results.append(validate_banner_poster_visible(
        submission, analysis,
        text_analysis=final_text_analysis
    ))
    results.append(validate_real_activity_scene(submission, analysis))
    results.append(validate_event_mode_matches(submission, analysis))
    results.append(validate_15_plus_participants_visible(submission, analysis))
    
    return results
