"""Duplicate detection with directory-level scanning."""
import logging
from typing import List, Dict, Optional, Any, Tuple

from event_validator.types import ValidationResult, EventSubmission
from event_validator.config.rules import SIMILARITY_RULES
from event_validator.types import ValidationConfig
from event_validator.utils.blob_directory_scanner import get_directory_scanner
from event_validator.utils.hashing import hamming_distance

logger = logging.getLogger(__name__)


# Global in-memory hash tracker for current batch
_batch_hash_tracker: Dict[str, Dict[str, Any]] = {}

# Global in-memory title tracker for current batch: (user_id, normalized_title) -> submission_id
_batch_title_tracker: Dict[Tuple[str, str], str] = {}


def reset_batch_hash_tracker():
    """Reset the batch hash and title trackers (call at start of new batch)."""
    global _batch_hash_tracker, _batch_title_tracker
    _batch_hash_tracker = {}
    _batch_title_tracker = {}


def validate_duplicate_detection(
    submission: EventSubmission,
    config: ValidationConfig,
    submission_id: Optional[str] = None
) -> ValidationResult:
    """
    Check for duplicate images within current batch and directory-level scanning.
    
    Performs:
    1. Batch-level duplicate detection (within current CSV)
    2. Directory-level duplicate detection (across all submissions in event_driven directory)
    3. SHA256 exact match detection
    4. pHash near-duplicate detection (configurable threshold)
    
    Args:
        submission: Event submission to check
        config: Validation configuration
        submission_id: Unique identifier for this submission (for duplicate messages)
    """
    global _batch_hash_tracker
    
    rule_name, points = SIMILARITY_RULES[0]
    
    logger.info(f"Checking: {rule_name} ({points} points)")
    
    if not submission.images:
        logger.info(f"  PASS: No images provided (no duplicates possible) | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,  # No images = no duplicates
            points_awarded=float(points),
            message=""
        )
    
    # Generate submission ID if not provided
    if not submission_id:
        original_data = getattr(submission, '_original_row_data', submission.row_data)
        submission_id = str(original_data.get('id', 'unknown'))
    
    # Get event_driven and academic_year for directory scanning
    original_data = getattr(submission, '_original_row_data', submission.row_data)
    event_driven = original_data.get('event_driven')
    academic_year = original_data.get('acadmic_year') or original_data.get('financial_year')
    
    # Initialize directory scanner
    directory_scanner = get_directory_scanner(phash_threshold=config.duplicate_phash_threshold)
    
    logger.debug(f"  Submission ID: {submission_id}")
    logger.debug(f"  Images to check: {len(submission.images)}")
    logger.debug(f"  Batch hash tracker size: {len(_batch_hash_tracker)}")
    logger.debug(f"  Event Driven: {event_driven}, Academic Year: {academic_year}")
    
    duplicate_found = False
    duplicate_messages = []
    
    # Track images within this submission to detect same-submission duplicates
    submission_image_hashes = set()
    
    # Check each submission image
    for i, img_data in enumerate(submission.images, 1):
        if not img_data.sha256:
            logger.debug(f"  Image {i}: No SHA256 hash, skipping")
            continue
        
        logger.debug(f"  Image {i}: Checking SHA256 {img_data.sha256[:16]}...")
        
        # Check if this image is a duplicate within the same submission
        if img_data.sha256 in submission_image_hashes:
            logger.info(f"  IGNORING: Image {i} is duplicate within same submission (same report) - ignoring")
            continue  # Skip this image, don't fail validation
        
        submission_image_hashes.add(img_data.sha256)
        
        # Step 1: Check batch-level duplicates (across different submissions)
        if img_data.sha256 in _batch_hash_tracker:
            # Duplicate found in batch!
            previous_submission = _batch_hash_tracker[img_data.sha256]
            previous_id = previous_submission.get('submission_id', 'unknown')
            
            # Only fail if it's from a different submission
            if previous_id != submission_id:
                duplicate_found = True
                duplicate_messages.append(
                    f"Image identical to submission {previous_id} (SHA256 match)"
                )
                
                logger.warning(
                    f"  DUPLICATE DETECTED (batch): Image {i} SHA256 {img_data.sha256[:16]}... "
                    f"matches submission {previous_id}"
                )
            else:
                logger.info(f"  IGNORING: Image {i} matches previous image in same submission - ignoring")
        else:
            # Step 2: Check directory-level duplicates
            directory_matches = directory_scanner.scan_directory_for_duplicates(
                target_sha256=img_data.sha256,
                target_phash=img_data.phash,
                event_driven=event_driven,
                academic_year=academic_year,
                submission_id=submission_id
            )
            
            if directory_matches:
                for match_path, match_type, similarity_score in directory_matches:
                    if match_type == 'exact':
                        duplicate_found = True
                        duplicate_messages.append(
                            f"Image identical to file in directory (SHA256 match): {match_path}"
                        )
                        logger.warning(
                            f"  DUPLICATE DETECTED (directory): Image {i} matches {match_path} (exact)"
                        )
                    elif match_type == 'near-duplicate':
                        duplicate_found = True
                        score_str = f" (similarity score: {similarity_score:.1f})" if similarity_score is not None else ""
                        duplicate_messages.append(
                            f"Image similar to file in directory (pHash match{score_str}): {match_path}"
                        )
                        logger.warning(
                            f"  NEAR-DUPLICATE DETECTED (directory): Image {i} similar to {match_path} "
                            f"(distance: {similarity_score})"
                        )
            
            # Step 3: Check pHash near-duplicates in batch
            if img_data.phash:
                for existing_hash, existing_data in _batch_hash_tracker.items():
                    existing_phash = existing_data.get('phash')
                    existing_submission_id = existing_data.get('submission_id', 'unknown')
                    if existing_phash and existing_phash != img_data.phash:
                        # Calculate Hamming distance
                        distance = hamming_distance(img_data.phash, existing_phash)
                        if distance <= config.duplicate_phash_threshold:
                            # Only fail if it's from a different submission
                            if existing_submission_id != submission_id:
                                duplicate_found = True
                                duplicate_messages.append(
                                    f"Image similar to submission {existing_submission_id} "
                                    f"(pHash distance: {distance}, threshold: {config.duplicate_phash_threshold})"
                                )
                                logger.warning(
                                    f"  NEAR-DUPLICATE (batch): Image {i} pHash distance {distance} "
                                    f"from submission {existing_submission_id}"
                                )
                                break
                            else:
                                logger.info(f"  IGNORING: Image {i} is similar to another image in same submission - ignoring")
                                break
            
            # Step 4: Store in batch tracker and directory cache
            if not duplicate_found:
                _batch_hash_tracker[img_data.sha256] = {
                    'submission_id': submission_id,
                    'phash': img_data.phash,
                    'path': str(img_data.path)
                }
                
                # Add to directory cache
                directory_scanner.add_file_to_cache(
                    sha256=img_data.sha256,
                    phash=img_data.phash,
                    file_path=str(img_data.path),
                    event_driven=event_driven,
                    academic_year=academic_year,
                    submission_id=submission_id
                )
                
                logger.debug(f"  Image {i}: Unique (stored in batch tracker and directory cache)")
    
    if duplicate_found:
        message = "Duplicate Check: " + "; ".join(duplicate_messages)
        logger.warning(f"  FAIL: Duplicate images found | Points: 0")
        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=0.0,
            message=message
        )
    else:
        logger.info(f"  PASS: No duplicates found | Points: {points}")
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=float(points),
            message=""
        )


def validate_duplicates(
    submission: EventSubmission,
    config: ValidationConfig,
    submission_id: Optional[str] = None
) -> List[ValidationResult]:
    """
    Run duplicate validation within current batch.
    
    Args:
        submission: Event submission
        config: Validation configuration
        submission_id: Unique identifier for this submission
    """
    results = []

    img_result = validate_duplicate_detection(submission, config, submission_id)
    if not img_result.passed:
        img_result.points_awarded = -10.0
    results.append(img_result)

    results.append(validate_duplicate_title(submission, config, submission_id))
    return results


def normalize_title(title: str) -> str:
    """Normalize title for duplicate checking (lowercase, strip, remove special chars)."""
    if not title:
        return ""
    import re

    cleaned = re.sub(r'[^a-z0-9]', '', title.lower())
    return cleaned


def validate_duplicate_title(
    submission: EventSubmission,
    config: ValidationConfig,
    submission_id: Optional[str] = None
) -> ValidationResult:
    """Check if the same user has submitted the same activity name."""
    global _batch_title_tracker

    rule_name, points = SIMILARITY_RULES[1]
    original_data = getattr(submission, '_original_row_data', submission.row_data)

    user_id = str(original_data.get('created_by', ''))
    if not user_id or user_id == 'nan':
        user_id = str(original_data.get('user_id', ''))

    activity_name = str(original_data.get('activity_name', ''))

    if not user_id or user_id == 'nan' or not activity_name or activity_name == 'nan':
        return ValidationResult(
            criterion=rule_name,
            passed=True,
            points_awarded=float(points),
            message="Skipped: Missing user_id or activity_name"
        )

    normalized = normalize_title(activity_name)
    tracker_key = (user_id, normalized)

    if tracker_key in _batch_title_tracker:
        previous_id = _batch_title_tracker[tracker_key]
        if previous_id == submission_id:
            return ValidationResult(
                criterion=rule_name,
                passed=True,
                points_awarded=float(points),
                message=""
            )

        return ValidationResult(
            criterion=rule_name,
            passed=False,
            points_awarded=-10.0,
            message=f"Duplicate title for same user (matches {previous_id})"
        )

    _batch_title_tracker[tracker_key] = submission_id or "unknown"
    return ValidationResult(
        criterion=rule_name,
        passed=True,
        points_awarded=float(points),
        message=""
    )
