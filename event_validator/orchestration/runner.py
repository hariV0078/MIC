"""Orchestration logic for event validation."""
import logging
import time
import os
from pathlib import Path
from typing import List, Optional
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from event_validator.types import EventSubmission, ValidationConfig, ValidationResult
from event_validator.extractors.pdf_extractor import extract_pdf_text
from event_validator.extractors.image_extractor import extract_images_from_paths
from event_validator.validators.theme_validator import validate_theme
from event_validator.validators.pdf_validator import validate_pdf
from event_validator.validators.image_validator import validate_images
from event_validator.validators.duplicate_validator import (
    validate_duplicates,
    reset_batch_hash_tracker
)
from event_validator.validators.gemini_client import GeminiClient
from event_validator.config.rules import ACCEPTANCE_THRESHOLD
from event_validator.utils.column_mapper import map_row_to_standard_format
from event_validator.utils.downloader import download_pdf, download_image, cleanup_all_files, DOWNLOAD_DIR
from event_validator.utils.file_operations import read_csv_from_path

logger = logging.getLogger(__name__)


def _get_score_column_name(criterion: str) -> str:
    """Map validation criterion to CSV column name for score breakdown."""
    # Map rule names to column names (camelCase format)
    column_mapping = {
        # Theme rules
        "Title/Objectives/Learning align to theme": "themeAlignmentScore",
        "Level matches duration": "levelDurationScore",
        "Participants reported > 15": "participantsReportedScore",
        "Year alignment (financial vs academic)": "yearAlignmentScore",
        # PDF rules
        "PDF title matches metadata": "pdfTitleScore",
        "Expert details present": "pdfExpertScore",
        "Learning outcomes align": "pdfLearningScore",
        "Objectives match": "pdfObjectivesScore",
        "Participant info matches": "pdfParticipantScore",
        # Image rules
        "GeoTag present": "imgGeotagScore",
        "Banner/Poster visible": "imgBannerScore",
        "Event scene is real activity": "imgRealActivityScore",
        "Event mode matches (online/offline)": "imgModeScore",
        "15+ participants visible": "imgParticipantsScore",
        # Similarity rules
        "Duplicate photo detection (filesystem)": "duplicateScore",
    }
    return column_mapping.get(criterion, criterion.replace(" ", "").replace("/", "") + "Score")


def _add_score_breakdown_to_row(enriched_row: dict, all_results: List[ValidationResult]) -> dict:
    """Add individual score breakdown columns to enriched row."""
    from event_validator.config.rules import get_rule_points, get_all_rules
    
    # Get all rules to know max points for each
    all_rules_dict = {}
    for category, rules in get_all_rules().items():
        for rule_name, max_points in rules:
            all_rules_dict[rule_name] = max_points
    
    # Initialize all score columns first (set to "0/0" if no result)
    all_score_columns = [
        'themeAlignmentScore', 'levelDurationScore', 'participantsReportedScore', 'yearAlignmentScore',
        'pdfTitleScore', 'pdfExpertScore', 'pdfLearningScore', 'pdfObjectivesScore', 'pdfParticipantScore',
        'imgGeotagScore', 'imgBannerScore', 'imgRealActivityScore', 'imgModeScore', 'imgParticipantsScore',
        'duplicateScore'
    ]
    for col in all_score_columns:
        if col not in enriched_row:
            enriched_row[col] = "0/0"
    
    # Add score columns for each result
    for result in all_results:
        column_name = _get_score_column_name(result.criterion)
        max_points = all_rules_dict.get(result.criterion, result.points_awarded)
        # Format: "2.0/2" or "0/7" (no .0 for zero)
        if result.points_awarded == 0:
            enriched_row[column_name] = f"0/{max_points}"
        else:
            enriched_row[column_name] = f"{result.points_awarded}.0/{max_points}"
    
    return enriched_row


def _calculate_heuristic_score(submission: EventSubmission) -> int:
    """
    Pre-scoring gate: Calculate a quick heuristic score without AI calls.
    This helps identify weak submissions early and can save 30-50% of API calls.
    
    Returns: Heuristic score (0-100) based on rule-based checks only.
    """
    score = 0
    row_data = submission.row_data
    
    # Check 1: PDF presence (mandatory) - 0 points if missing, but don't penalize in heuristic
    if submission.pdf_data and submission.pdf_data.text:
        # Quick keyword checks in PDF
        pdf_text_lower = submission.pdf_data.text.lower()
        has_expert_keywords = any(kw in pdf_text_lower for kw in [
            'expert', 'speaker', 'facilitator', 'instructor', 'trainer',
            'resource person', 'keynote', 'presenter'
        ])
        if has_expert_keywords:
            score += 7  # Expert details likely present
    
    # Check 2: Images presence (at least 1 mandatory)
    if submission.images and len(submission.images) > 0:
        score += 2  # Basic image presence
    
    # Check 3: Participants count (rule-based, no AI)
    try:
        participants_str = str(row_data.get('Participants', '0')).strip()
        participants = int(float(participants_str))
        if participants > 15:
            score += 12  # Participants > 15
    except (ValueError, TypeError):
        pass
    
    # Check 4: Level-duration match (rule-based, no AI)
    level = str(row_data.get('Level', '')).strip()
    duration = str(row_data.get('Duration', '')).strip()
    if level and duration:
        try:
            from event_validator.utils.column_mapper import validate_level_duration_match, LEVEL_DEFINITIONS
            level_int = int(level)
            # Parse duration
            import re
            duration_lower = duration.lower()
            duration_lower = duration_lower.replace('hours', '').replace('hour', '').replace('hrs', '').replace('hr', '')
            duration_lower = duration_lower.replace('minutes', '').replace('minute', '').replace('mins', '').replace('min', '')
            duration_lower = duration_lower.replace('h', '').replace('m', '')
            numbers = re.findall(r'\d+\.?\d*', duration_lower)
            if numbers:
                duration_hours = float(numbers[0])
                if 'min' in duration.lower() or 'm' in duration.lower():
                    duration_hours = duration_hours / 60.0
                if level_int in LEVEL_DEFINITIONS and validate_level_duration_match(level_int, duration_hours):
                    score += 11  # Level matches duration
        except (ValueError, TypeError):
            pass
    
    # Check 5: Basic theme/objectives/learning outcomes presence (not alignment, just presence)
    theme = str(row_data.get('Theme', '')).strip()
    objectives = str(row_data.get('Objectives', '')).strip()
    learning_outcomes = str(row_data.get('Learning Outcomes', '')).strip()
    if theme and objectives and learning_outcomes:
        score += 5  # Basic fields present (alignment checked by AI)
    
    return min(score, 100)  # Cap at 100


def process_submission(
    row_data: dict,
    config: ValidationConfig,
    gemini_client: GeminiClient
) -> EventSubmission:
    """
    Process a single event submission through the validation pipeline.
    """
    # Map actual CSV columns to standard format
    mapped_data = map_row_to_standard_format(row_data)
    
    # Use mapped data for validation, but keep original for output
    submission = EventSubmission(row_data=mapped_data)
    submission._original_row_data = row_data  # Store original for output
    
    # Get event_driven and academic_year for URL resolution
    original_data = getattr(submission, '_original_row_data', row_data)
    event_driven = original_data.get('event_driven')
    academic_year = original_data.get('acadmic_year') or original_data.get('financial_year')
    
    # Extract PDF data (MANDATORY)
    pdf_path_str = mapped_data.get('PDF Path', '').strip()
    pdf_missing = True  # Track if PDF is missing
    if pdf_path_str:
        # Check if it's a URL (Azure Blob Storage) or local path
        if pdf_path_str.startswith('http'):
            # Download from Azure Blob Storage URL with progressive probing
            temp_pdf_path = download_pdf(
                pdf_path_str,
                event_driven=event_driven,
                academic_year=academic_year
            )
            if temp_pdf_path:
                logger.info(f"Extracting PDF from downloaded file: {temp_pdf_path}")
                submission.pdf_data = extract_pdf_text(temp_pdf_path)
                if submission.pdf_data:  # PDF successfully extracted
                    pdf_missing = False
                # Note: PDF file is saved in current directory (downloaded_files/)
                # It is kept for potential future use and can be cleaned up manually if needed
            else:
                logger.warning(f"Failed to download PDF from URL: {pdf_path_str}")
        else:
            pdf_path = Path(pdf_path_str)
            if pdf_path.exists():
                logger.info(f"Extracting PDF: {pdf_path}")
                submission.pdf_data = extract_pdf_text(pdf_path)
                if submission.pdf_data:  # PDF successfully extracted
                    pdf_missing = False
            else:
                logger.warning(f"PDF file not found: {pdf_path}")
    else:
        logger.warning("PDF Path is empty - PDF is mandatory")
    
    # Extract image data (AT LEAST 1 IMAGE MANDATORY)
    image_paths_str = mapped_data.get('Image Paths', '').strip()
    images_missing = True  # Track if images are missing
    if image_paths_str:
        # Support comma-separated or semicolon-separated paths
        separators = [',', ';']
        paths = [image_paths_str]
        for sep in separators:
            if sep in image_paths_str:
                paths = [p.strip() for p in image_paths_str.split(sep)]
                break
        
        # Handle both URLs and local paths
        image_paths = []
        temp_files = []  # Track temp files for cleanup
        
        for p in paths:
            p = p.strip()
            # Skip empty or invalid paths
            invalid_paths = {'', '0', 'null', 'none', 'n/a'}
            if not p or p.lower() in invalid_paths:
                continue
                
            if p.startswith('http'):
                # Download from Azure Blob Storage URL with progressive probing
                temp_image_path = download_image(
                    p,
                    event_driven=event_driven,
                    academic_year=academic_year
                )
                if temp_image_path:
                    image_paths.append(temp_image_path)
                    temp_files.append(temp_image_path)
                else:
                    logger.warning(f"Failed to download image from URL: {p}")
            else:
                image_paths.append(Path(p))
        
        if image_paths:
            logger.info(f"Extracting {len(image_paths)} images")
            submission.images = extract_images_from_paths(image_paths)
            if submission.images and len(submission.images) > 0:  # At least 1 image successfully extracted
                images_missing = False
            
            # Note: Files are saved in current directory (downloaded_files/)
            # They are kept for Groq Vision analysis and can be cleaned up manually if needed
            # No automatic cleanup to prevent "file not found" errors during validation
    else:
        logger.warning("Image Paths is empty - At least 1 image is mandatory")
    
    # Pre-scoring gate: Quick heuristic checks before expensive AI calls
    # This can save 30-50% of API calls for weak submissions
    heuristic_score = _calculate_heuristic_score(submission)
    ACCEPTANCE_THRESHOLD = 60  # From config
    if heuristic_score < 25:  # If heuristic score is very low, skip some AI calls
        logger.warning(f"Pre-scoring gate: Heuristic score {heuristic_score} < 25. Submission likely to fail, but proceeding with full validation.")
    
    # Start timing for this submission
    submission_start_time = time.time()
    
    # Get submission ID for logging (needed for budget tracking)
    original_data = getattr(submission, '_original_row_data', submission.row_data)
    submission_id = str(original_data.get('id', original_data.get('eventId', 'unknown')))
    submission_title = original_data.get('activity_name', 'Unknown Event')
    
    # Initialize request budget for this submission
    from event_validator.utils.request_budget import get_budget
    budget = get_budget(submission_id)
    
    # Run validations
    all_results: List[ValidationResult] = []
    
    logger.info("=" * 80)
    logger.info(f"VALIDATION START | Submission ID: {submission_id} | Title: {submission_title}")
    logger.info(f"Pre-scoring heuristic score: {heuristic_score}/100")
    logger.info("=" * 80)
    
    # Initialize scoring variables (must be set even if validations are skipped)
    theme_points = 0
    theme_results = []
    pdf_points = 0
    pdf_results = []
    image_points = 0
    image_results = []
    duplicate_points = 0
    duplicate_results = []
    
    # Removed stagger delay - rate limiter handles spacing automatically
    # With 4 concurrent calls and 145 RPM, no need for additional delays
    
    # Theme validation
    logger.info("─" * 80)
    logger.info("THEME VALIDATION (33 points total - Year alignment disabled)")
    logger.info("─" * 80)
    
    # Check budget before theme validation (1 API call)
    if not budget.can_make_call("theme_alignment"):
        logger.warning(f"Budget exhausted before theme validation. Skipping API call.")
        # Create failure result
        from event_validator.config.rules import THEME_RULES
        rule_name, points = THEME_RULES[0]
        theme_results = [ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0,
            message="Theme validation skipped: API call budget exhausted"
        )]
    else:
        theme_results = validate_theme(submission, gemini_client)
        # Record API call (theme validation makes 1 call)
        budget.record_call("theme_alignment", success=True)
    all_results.extend(theme_results)
    
    # Log theme validation results
    theme_points = sum(r.points_awarded for r in theme_results)
    theme_passed = sum(1 for r in theme_results if r.passed)
    theme_total = len(theme_results)
    logger.info(f"Theme Validation Summary: {theme_passed}/{theme_total} passed | Points: {theme_points}/33 (Year alignment disabled)")
    for result in theme_results:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        logger.info(f"  [{status}] {result.criterion}: {result.points_awarded} points | {result.message or 'OK'}")
    
    # Removed delay - parallel processing handles rate limiting better
    
    # PDF validation
    logger.info("─" * 80)
    logger.info("PDF VALIDATION (25 points total)")
    logger.info("─" * 80)
    if submission.pdf_data:
        # Check budget before PDF validation (1 API call)
        if not budget.can_make_call("pdf_validation"):
            logger.warning(f"Budget exhausted before PDF validation. Skipping API call.")
            # Create failure results
            from event_validator.config.rules import PDF_RULES
            pdf_results = []
            for rule_name, points in PDF_RULES:
                pdf_results.append(ValidationResult(
                    criterion=rule_name,
                    passed=False,
                    points_awarded=0,
                    message="PDF validation skipped: API call budget exhausted"
                ))
        else:
            pdf_results = validate_pdf(submission, gemini_client)
            # Record API call (PDF validation makes 1 unified call)
            budget.record_call("pdf_validation", success=True)
        all_results.extend(pdf_results)
        
        # Log PDF validation results
        pdf_points = sum(r.points_awarded for r in pdf_results)
        pdf_passed = sum(1 for r in pdf_results if r.passed)
        pdf_total = len(pdf_results)
        logger.info(f"PDF Validation Summary: {pdf_passed}/{pdf_total} passed | Points: {pdf_points}/25")
        for result in pdf_results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            logger.info(f"  [{status}] {result.criterion}: {result.points_awarded} points | {result.message or 'OK'}")
        
        # Removed delay - parallel processing handles rate limiting better
    else:
        logger.warning("Skipping PDF validation - no PDF data available")
        # Create failure result for missing PDF
        from event_validator.config.rules import PDF_RULES
        pdf_total_points = sum(points for _, points in PDF_RULES)
        missing_pdf_result = ValidationResult(
            criterion="PDF Validation",
            passed=False,
            points_awarded=0,
            message="PDF file missing or could not be downloaded"
        )
        pdf_results = [missing_pdf_result]
        all_results.extend(pdf_results)
        pdf_points = 0
        pdf_total = len(PDF_RULES)
        logger.info(f"PDF Validation Summary: 0/{pdf_total} passed | Points: {pdf_points}/25 (PDF missing or unreadable)")
        logger.info(f"  [✗ FAIL] PDF Validation: 0 points | PDF file missing or could not be downloaded")
    
    # ═══════════════════════════════════════════════════════════════
    # KILL SWITCH ENFORCEMENT (Types 1, 2, 4)
    # If Flow 2 failed, zero out Theme + Image scores immediately
    # ═══════════════════════════════════════════════════════════════
    if submission.kill_switch:
        logger.warning("═" * 80)
        logger.warning("KILL SWITCH ACTIVE: Flow 2 (PDF Relevance) failed.")
        logger.warning("Zeroing Theme scores and skipping Image analysis.")
        logger.warning("═" * 80)
        
        # Zero out theme scores: replace existing theme results
        from event_validator.config.rules import THEME_RULES, IMAGE_RULES
        
        # Remove existing theme results from all_results
        all_results = [r for r in all_results if r not in theme_results]
        theme_results = []
        for rule_name, points in THEME_RULES:
            theme_results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="Kill switch active: PDF content irrelevant to activity (Flow 2 Fail)"
            ))
        all_results.extend(theme_results)
        theme_points = 0
        logger.info(f"Theme scores zeroed: 0/{len(THEME_RULES)} passed | Points: 0")
        
        # Zero out image scores: skip analysis entirely
        image_results = []
        for rule_name, points in IMAGE_RULES:
            image_results.append(ValidationResult(
                criterion=rule_name,
                passed=False,
                points_awarded=0,
                message="Kill switch active: Image analysis skipped (Flow 2 Fail)"
            ))
        all_results.extend(image_results)
        image_points = 0
        logger.info(f"Image scores zeroed: 0/{len(IMAGE_RULES)} passed | Points: 0 (SKIPPED)")
    else:
        # Image validation (only if kill switch is NOT active)
        logger.info("─" * 80)
        logger.info("IMAGE VALIDATION (20 points total)")
        logger.info("─" * 80)
        if submission.images:
            # Check budget before image validation (1 API call per image, but we use first image)
            if not budget.can_make_call("image_validation"):
                logger.warning(f"Budget exhausted before image validation. Skipping API call.")
                # Create failure results
                from event_validator.config.rules import IMAGE_RULES
                image_results = []
                for rule_name, points in IMAGE_RULES:
                    image_results.append(ValidationResult(
                        criterion=rule_name,
                        passed=False,
                        points_awarded=0,
                        message="Image validation skipped: API call budget exhausted"
                    ))
            else:
                image_results = validate_images(submission, gemini_client)
                # Record API call (image validation makes 1 call per image, but optimized to 1)
                budget.record_call("image_validation", success=True)
            all_results.extend(image_results)
            
            # Log image validation results
            image_points = sum(r.points_awarded for r in image_results)
            image_passed = sum(1 for r in image_results if r.passed)
            image_total = len(image_results)
            logger.info(f"Image Validation Summary: {image_passed}/{image_total} passed | Points: {image_points}/20")
            for result in image_results:
                status = "✓ PASS" if result.passed else "✗ FAIL"
                logger.info(f"  [{status}] {result.criterion}: {result.points_awarded} points | {result.message or 'OK'}")
        else:
            logger.warning("Skipping image validation - no images available")
            # Create failure result for missing images
            from event_validator.config.rules import IMAGE_RULES
            image_total_points = sum(points for _, points in IMAGE_RULES)
            missing_image_result = ValidationResult(
                criterion="Image Validation",
                passed=False,
                points_awarded=0,
                message="Event photos missing or invalid"
            )
            image_results = [missing_image_result]
            all_results.extend(image_results)
            image_points = 0
            image_total = len(IMAGE_RULES)
            logger.info(f"Image Validation Summary: 0/{image_total} passed | Points: {image_points}/20 (images missing or invalid)")
            logger.info(f"  [✗ FAIL] Image Validation: 0 points | Event photos missing or invalid")
    
    # Duplicate validation (within batch)
    logger.info("─" * 80)
    logger.info("DUPLICATE VALIDATION (15 points total)")
    logger.info("─" * 80)
    duplicate_results = validate_duplicates(submission, config, submission_id)
    all_results.extend(duplicate_results)
    
    # Log duplicate validation results
    duplicate_points = sum(r.points_awarded for r in duplicate_results)
    duplicate_passed = sum(1 for r in duplicate_results if r.passed)
    duplicate_total = len(duplicate_results)
    logger.info(f"Duplicate Validation Summary: {duplicate_passed}/{duplicate_total} passed | Points: {duplicate_points}/15")
    for result in duplicate_results:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        logger.info(f"  [{status}] {result.criterion}: {result.points_awarded} points | {result.message or 'OK'}")
    
    # Calculate overall score
    logger.info("─" * 80)
    logger.info("SCORING SUMMARY")
    logger.info("─" * 80)
    total_points = sum(r.points_awarded for r in all_results)
    submission.overall_score = total_points
    
    # Log score breakdown
    total_passed = sum(1 for r in all_results if r.passed)
    total_rules = len(all_results)
    logger.info(f"Total Rules: {total_rules} | Passed: {total_passed} | Failed: {total_rules - total_passed}")
    logger.info(f"Score Breakdown:")
    logger.info(f"  Theme:    {theme_points}/33 (Year alignment disabled)")
    logger.info(f"  PDF:      {pdf_points}/25")
    logger.info(f"  Image:    {image_points}/20")
    logger.info(f"  Duplicate: {duplicate_points}/15")
    logger.info(f"  ─────────────────────")
    logger.info(f"  TOTAL:    {total_points}/93 (max possible - Year alignment disabled)")
    
    # Determine status
    threshold = config.acceptance_threshold or ACCEPTANCE_THRESHOLD
    
    # Check mandatory requirements: PDF is mandatory, at least 1 image is mandatory
    # Set status: Reopen if mandatory files are missing, otherwise Accepted/Rejected based on threshold
    if pdf_missing:
        submission.status = "Reopen"
        logger.warning(f"PDF is mandatory but missing - Status set to: Reopen")
    elif images_missing:
        submission.status = "Reopen"
        logger.warning(f"At least 1 image is mandatory but missing - Status set to: Reopen")
    elif total_points >= threshold:
        submission.status = "Accepted"
    else:
        submission.status = "Rejected"
    
    logger.info(f"Acceptance Threshold: {threshold} points")
    logger.info(f"Final Status: {submission.status} ({'≥' if total_points >= threshold else '<'} {threshold} points)")
    
    # Generate requirements not met message in specified format:
    # "Title: ...; Participants: ...; Theme: ...; PDF: ...; Image Analysis: ..."
    failed_results = [r for r in all_results if not r.passed]
    if failed_results:
        # Map criteria to category names
        def get_category_name(criterion: str) -> str:
            """Map validation criterion to category name."""
            criterion_lower = criterion.lower()
            if "title" in criterion_lower or "objectives" in criterion_lower or "learning" in criterion_lower:
                if "theme" in criterion_lower or "align" in criterion_lower:
                    return "Theme"
                elif "pdf" in criterion_lower:
                    return "PDF"
                else:
                    return "Title"
            elif "participant" in criterion_lower:
                if "pdf" in criterion_lower or "visible" in criterion_lower:
                    return "Image Analysis"
                else:
                    return "Participants"
            elif "pdf" in criterion_lower or "expert" in criterion_lower:
                return "PDF"
            elif "geotag" in criterion_lower or "banner" in criterion_lower or "poster" in criterion_lower or "event scene" in criterion_lower or "event mode" in criterion_lower or "visible" in criterion_lower:
                return "Image Analysis"
            elif "duplicate" in criterion_lower:
                return "Image Analysis"
            elif "level" in criterion_lower or "duration" in criterion_lower:
                return "Title"
            else:
                return "Other"
        
        # Format failure messages (remove rule name prefix, keep only the reason)
        def format_failure_message(result: ValidationResult) -> str:
            """Format failure message without rule name prefix."""
            message = result.message.strip() if result.message else ""
            criterion = result.criterion
            
            # Remove rule name prefix if present (e.g., "PDF title matches metadata: Title not found" -> "Title not found")
            if message:
                # Check if message starts with criterion name
                if message.lower().startswith(criterion.lower()):
                    # Remove the prefix
                    remaining = message[len(criterion):].strip()
                    if remaining.startswith(":"):
                        remaining = remaining[1:].strip()
                    if remaining:
                        return remaining
                return message
            
            # If no message, create a default one based on criterion
            if "title" in criterion.lower():
                if "pdf" in criterion.lower():
                    return "Title not found in PDF"
                else:
                    return "Title validation failed"
            elif "participant" in criterion.lower():
                if "pdf" in criterion.lower():
                    return "Participant information missing in PDF"
                elif "visible" in criterion.lower():
                    return "Insufficient participants visible in images"
                else:
                    return "Participant count validation failed"
            elif "theme" in criterion.lower() or "align" in criterion.lower():
                return "Theme validation failed"
            elif "expert" in criterion.lower():
                return "Expert details missing in PDF"
            elif "learning" in criterion.lower():
                return "Learning outcomes not specified in PDF"
            elif "objectives" in criterion.lower():
                return "Objectives not clearly stated in PDF"
            elif "geotag" in criterion.lower():
                return "No GPS location data in images"
            elif "banner" in criterion.lower() or "poster" in criterion.lower():
                return "Banner or poster not visible"
            elif "real activity" in criterion.lower():
                return "Event scene does not show real activity"
            elif "mode" in criterion.lower():
                return "Event mode mismatch in images"
            elif "duplicate" in criterion.lower():
                return "Duplicate images detected"
            elif "level" in criterion.lower() or "duration" in criterion.lower():
                return "Level or duration validation failed"
            else:
                return criterion
        
        # Group failures by category
        category_failures = {}
        for result in failed_results:
            category = get_category_name(result.criterion)
            failure_msg = format_failure_message(result)
            
            if category not in category_failures:
                category_failures[category] = []
            category_failures[category].append(failure_msg)
        
        # Format as "Category: failure1; failure2; ..."
        category_strings = []
        for category in ["Title", "Participants", "Theme", "PDF", "Image Analysis"]:
            if category in category_failures:
                failures = category_failures[category]
                if len(failures) == 1:
                    category_strings.append(f"{category}: {failures[0]}")
                else:
                    # Multiple failures in same category: "Category: failure1; failure2; failure3"
                    category_strings.append(f"{category}: {'; '.join(failures)}")
        
        # Add any other categories not in the standard list
        for category in category_failures:
            if category not in ["Title", "Participants", "Theme", "PDF", "Image Analysis"]:
                failures = category_failures[category]
                if len(failures) == 1:
                    category_strings.append(f"{category}: {failures[0]}")
                else:
                    category_strings.append(f"{category}: {'; '.join(failures)}")
        
        requirements_not_met = "; ".join(category_strings)
        submission.requirements_not_met = requirements_not_met
        
        logger.info("─" * 80)
        logger.info("REQUIREMENTS NOT MET:")
        logger.info("─" * 80)
        for i, result in enumerate(failed_results, 1):
            logger.info(f"  {i}. {result.criterion}")
            if result.message:
                logger.info(f"     Reason: {result.message}")
    else:
        submission.requirements_not_met = ""
        logger.info("─" * 80)
        logger.info("REQUIREMENTS NOT MET: None (All requirements met!)")
        logger.info("─" * 80)
    
    submission.validation_results = all_results
    
    # Calculate elapsed time
    submission_elapsed_time = time.time() - submission_start_time
    submission_elapsed_minutes = int(submission_elapsed_time // 60)
    submission_elapsed_seconds = submission_elapsed_time % 60
    
    logger.info("=" * 80)
    logger.info(f"VALIDATION COMPLETE | Submission ID: {submission_id} | Score: {total_points}/100 | Status: {submission.status}")
    if submission_elapsed_minutes > 0:
        logger.info(f"Time taken: {submission_elapsed_minutes}m {submission_elapsed_seconds:.2f}s ({submission_elapsed_time:.2f} seconds)")
    else:
        logger.info(f"Time taken: {submission_elapsed_seconds:.2f} seconds")
    logger.info("=" * 80)
    
    return submission


def process_csv(
    input_csv_path: Path,
    output_csv_path: Path,
    config: ValidationConfig,
    gemini_api_key: Optional[str] = None,
    groq_api_key: Optional[str] = None
) -> None:
    """
    Process all rows in CSV and write enriched output.
    """
    # Start timing for entire CSV processing
    csv_start_time = time.time()
    csv_start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Clear downloaded_files directory at the start of new processing
    logger.info("Clearing downloaded_files directory for new processing run...")
    deleted_count = cleanup_all_files()
    if deleted_count > 0:
        logger.info(f"Cleared {deleted_count} file(s) from downloaded_files directory")
    else:
        logger.info("downloaded_files directory is already empty")
    
    # Reset circuit breakers to ensure fresh state for each run
    from event_validator.utils.circuit_breaker import reset_gemini_circuit_breaker, reset_groq_circuit_breaker
    reset_gemini_circuit_breaker()
    reset_groq_circuit_breaker()
    logger.info("Circuit breakers reset for new processing run")
    
    # Initialize Gemini client with Groq fallback
    if gemini_api_key is None:
        gemini_api_key = config.gemini_api_key if hasattr(config, 'gemini_api_key') else config.groq_api_key
    if groq_api_key is None:
        groq_api_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
    gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_api_key)
    
    if not gemini_client.client:
        logger.warning("Gemini client not initialized. Some validations may fail.")
    
    # Read input file (CSV or Excel)
    if not input_csv_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_csv_path}")
    
    # Use file_operations to read CSV or Excel files
    logger.info(f"Reading input file: {input_csv_path.name}")
    df = read_csv_from_path(str(input_csv_path))
    
    # Convert DataFrame to list of dictionaries
    rows = df.to_dict('records')
    fieldnames = list(df.columns)
    
    logger.info("=" * 80)
    logger.info(f"FILE PROCESSING STARTED | Input: {input_csv_path.name} | Rows: {len(rows)} | Start Time: {csv_start_datetime}")
    logger.info("=" * 80)
    
    # Reset batch hash tracker at start of new batch
    reset_batch_hash_tracker()
    
    # Process rows in parallel for better performance
    # Optimized for 8-minute target: 12 workers × 6 concurrent Gemini calls = 72 concurrent API calls
    # With 148 RPM (145 effective after 98% safety), this provides maximum safe throughput
    max_workers = min(int(os.getenv('DEFAULT_MAX_WORKERS', '12')), len(rows))
    from event_validator.utils.concurrency import GEMINI_MAX_CONCURRENT
    logger.info(f"Processing {len(rows)} submissions with {max_workers} parallel workers (Gemini concurrency: {GEMINI_MAX_CONCURRENT})")
    
    enriched_rows = [None] * len(rows)  # Pre-allocate list to maintain order
    
    def process_single_row(row_data: dict, index: int) -> tuple[int, dict]:
        """Process a single row and return its index and result."""
        try:
            submission = process_submission(row_data, config, gemini_client)
            
            # Create enriched row (use original row data)
            enriched_row = getattr(submission, '_original_row_data', row_data).copy()
            enriched_row['Overall Score'] = str(submission.overall_score)
            enriched_row['Status'] = submission.status
            enriched_row['Requirements Not Met'] = submission.requirements_not_met
            
            # Add individual score breakdown columns
            enriched_row = _add_score_breakdown_to_row(enriched_row, submission.validation_results)
            
            logger.info(
                f"Submission {index + 1}/{len(rows)}: Score={submission.overall_score}, "
                f"Status={submission.status}"
            )
            
            return (index, enriched_row)
        except Exception as e:
            logger.error(f"Error processing submission {index + 1}: {e}", exc_info=True)
            # Add row with error status
            enriched_row = row_data.copy()
            enriched_row['Overall Score'] = "0"
            enriched_row['Status'] = "Error"
            enriched_row['Requirements Not Met'] = f"Processing error: {str(e)}"
            # Initialize empty score columns for error cases
            score_columns = [
                'themeAlignmentScore', 'levelDurationScore', 'participantsReportedScore', 'yearAlignmentScore',
                'pdfTitleScore', 'pdfExpertScore', 'pdfLearningScore', 'pdfObjectivesScore', 'pdfParticipantScore',
                'imgGeotagScore', 'imgBannerScore', 'imgRealActivityScore', 'imgModeScore', 'imgParticipantsScore',
                'duplicateScore'
            ]
            for col in score_columns:
                enriched_row[col] = "0/0"
            return (index, enriched_row)
    
    # Process in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_index = {
            executor.submit(process_single_row, row, i): i 
            for i, row in enumerate(rows)
        }
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_index):
            completed += 1
            try:
                index, enriched_row = future.result()
                enriched_rows[index] = enriched_row
                if completed % 10 == 0 or completed == len(rows):
                    logger.info(f"Progress: {completed}/{len(rows)} submissions completed")
            except Exception as e:
                original_index = future_to_index[future]
                logger.error(f"Unexpected error processing submission {original_index + 1}: {e}", exc_info=True)
                # Create error row
                error_row = rows[original_index].copy()
                error_row['Overall Score'] = "0"
                error_row['Status'] = "Error"
                error_row['Requirements Not Met'] = f"Unexpected error: {str(e)}"
                # Initialize empty score columns for error cases
                score_columns = [
                    'themeAlignmentScore', 'levelDurationScore', 'participantsReportedScore', 'yearAlignmentScore',
                    'pdfTitleScore', 'pdfExpertScore', 'pdfLearningScore', 'pdfObjectivesScore', 'pdfParticipantScore',
                    'imgGeotagScore', 'imgBannerScore', 'imgRealActivityScore', 'imgModeScore', 'imgParticipantsScore',
                    'duplicateScore'
                ]
                for col in score_columns:
                    error_row[col] = "0/0"
                enriched_rows[original_index] = error_row
    
    # Filter out any None values (shouldn't happen, but safety check)
    enriched_rows = [row for row in enriched_rows if row is not None]
    
    # Write output CSV with proper field ordering
    # Ensure required fields are always present
    # Add score breakdown columns
    score_columns = [
        'themeAlignmentScore', 'levelDurationScore', 'participantsReportedScore', 'yearAlignmentScore',
        'pdfTitleScore', 'pdfExpertScore', 'pdfLearningScore', 'pdfObjectivesScore', 'pdfParticipantScore',
        'imgGeotagScore', 'imgBannerScore', 'imgRealActivityScore', 'imgModeScore', 'imgParticipantsScore',
        'duplicateScore'
    ]
    output_fieldnames = list(fieldnames) + ['Overall Score', 'Status', 'Requirements Not Met'] + score_columns
    
    # Remove duplicates while preserving order
    seen = set()
    output_fieldnames = [f for f in output_fieldnames if not (f in seen or seen.add(f))]
    
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv_path, 'w', encoding='utf-8-sig', newline='') as f:  # utf-8-sig for Excel compatibility
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(enriched_rows)
    
    # Calculate elapsed time
    csv_elapsed_time = time.time() - csv_start_time
    csv_elapsed_minutes = int(csv_elapsed_time // 60)
    csv_elapsed_seconds = csv_elapsed_time % 60
    csv_end_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Calculate average time per submission
    avg_time_per_submission = csv_elapsed_time / len(enriched_rows) if enriched_rows else 0
    
    logger.info("=" * 80)
    logger.info(f"FILE PROCESSING COMPLETED | Output: {output_csv_path.name} | Rows processed: {len(enriched_rows)}")
    logger.info(f"Start Time: {csv_start_datetime} | End Time: {csv_end_datetime}")
    if csv_elapsed_minutes > 0:
        logger.info(f"Total Time: {csv_elapsed_minutes}m {csv_elapsed_seconds:.2f}s ({csv_elapsed_time:.2f} seconds)")
    else:
        logger.info(f"Total Time: {csv_elapsed_seconds:.2f} seconds")
    logger.info(f"Average Time per Submission: {avg_time_per_submission:.2f} seconds")
    logger.info("=" * 80)

