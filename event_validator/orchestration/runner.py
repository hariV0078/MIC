"""Orchestration logic for event validation."""
import logging
import time
import os
from pathlib import Path
from typing import List
import csv

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
from event_validator.utils.downloader import download_pdf, download_image

logger = logging.getLogger(__name__)


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
    
    # Run validations
    all_results: List[ValidationResult] = []
    
    # Get submission ID for logging
    original_data = getattr(submission, '_original_row_data', submission.row_data)
    submission_id = str(original_data.get('id', original_data.get('eventId', 'unknown')))
    submission_title = original_data.get('activity_name', 'Unknown Event')
    
    logger.info("=" * 80)
    logger.info(f"VALIDATION START | Submission ID: {submission_id} | Title: {submission_title}")
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
    
    # Theme validation
    logger.info("─" * 80)
    logger.info("THEME VALIDATION (33 points total - Year alignment disabled)")
    logger.info("─" * 80)
    theme_results = validate_theme(submission, gemini_client)
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
        pdf_results = validate_pdf(submission, gemini_client)
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
    
    # Image validation
    logger.info("─" * 80)
    logger.info("IMAGE VALIDATION (14 points total - Geotag validation disabled)")
    logger.info("─" * 80)
    if submission.images:
        image_results = validate_images(submission, gemini_client)
        all_results.extend(image_results)
        
        # Log image validation results
        image_points = sum(r.points_awarded for r in image_results)
        image_passed = sum(1 for r in image_results if r.passed)
        image_total = len(image_results)
        logger.info(f"Image Validation Summary: {image_passed}/{image_total} passed | Points: {image_points}/14 (Geotag validation disabled)")
        for result in image_results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            logger.info(f"  [{status}] {result.criterion}: {result.points_awarded} points | {result.message or 'OK'}")
        
        # Removed delay - parallel processing handles rate limiting better
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
    logger.info(f"  Image:    {image_points}/14 (Geotag validation disabled)")
    logger.info(f"  Duplicate: {duplicate_points}/15")
    logger.info(f"  ─────────────────────")
    logger.info(f"  TOTAL:    {total_points}/87 (max possible with disabled validations)")
    
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
    
    # Generate requirements not met message
    failed_results = [r for r in all_results if not r.passed]
    if failed_results:
        requirements_not_met = "; ".join([
            f"{r.criterion}: {r.message}" if r.message else r.criterion
            for r in failed_results
        ])
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
    
    logger.info("=" * 80)
    logger.info(f"VALIDATION COMPLETE | Submission ID: {submission_id} | Score: {total_points}/100 | Status: {submission.status}")
    logger.info("=" * 80)
    
    return submission


def process_csv(
    input_csv_path: Path,
    output_csv_path: Path,
    config: ValidationConfig
) -> None:
    """
    Process all rows in CSV and write enriched output.
    """
    # Initialize Gemini client with Groq fallback
    gemini_api_key = config.gemini_api_key if hasattr(config, 'gemini_api_key') else config.groq_api_key
    groq_api_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
    gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_api_key)
    
    if not gemini_client.client:
        logger.warning("Gemini client not initialized. Some validations may fail.")
    
    # Read input CSV
    if not input_csv_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv_path}")
    
    rows = []
    fieldnames = []
    
    with open(input_csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    
    logger.info(f"Processing {len(rows)} submissions...")
    
    # Reset batch hash tracker at start of new batch
    reset_batch_hash_tracker()
    
    # Process each row
    enriched_rows = []
    for i, row in enumerate(rows, 1):
        logger.info(f"Processing submission {i}/{len(rows)}")
        try:
            submission = process_submission(row, config, gemini_client)
            
            # Create enriched row (use original row data)
            enriched_row = getattr(submission, '_original_row_data', row).copy()
            enriched_row['Overall Score'] = str(submission.overall_score)
            enriched_row['Status'] = submission.status
            enriched_row['Requirements Not Met'] = submission.requirements_not_met
            
            enriched_rows.append(enriched_row)
            
            logger.info(
                f"Submission {i}: Score={submission.overall_score}, "
                f"Status={submission.status}"
            )
        except Exception as e:
            logger.error(f"Error processing submission {i}: {e}", exc_info=True)
            # Add row with error status
            enriched_row = row.copy()
            enriched_row['Overall Score'] = "0"
            enriched_row['Status'] = "Error"
            enriched_row['Requirements Not Met'] = f"Processing error: {str(e)}"
            enriched_rows.append(enriched_row)
    
    # Write output CSV with proper field ordering
    # Ensure required fields are always present
    output_fieldnames = list(fieldnames) + ['Overall Score', 'Status', 'Requirements Not Met']
    
    # Remove duplicates while preserving order
    seen = set()
    output_fieldnames = [f for f in output_fieldnames if not (f in seen or seen.add(f))]
    
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv_path, 'w', encoding='utf-8-sig', newline='') as f:  # utf-8-sig for Excel compatibility
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(enriched_rows)
    
    logger.info(f"Output CSV written to: {output_csv_path}")
    logger.info(f"Total rows processed: {len(enriched_rows)}")
    logger.info(f"Output fields: {len(output_fieldnames)} columns including 'Overall Score', 'Status', 'Requirements Not Met'")

