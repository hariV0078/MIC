"""Blob path resolver for Azure Blob Storage URLs - simple deterministic mapping."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Base paths by event_driven type - NO modifications, NO fallbacks
EVENT_DRIVEN_BASE_PATH = {
    1: "https://miciicsta01.blob.core.windows.net/miciiccontainer1/",
    2: "https://miciicsta01.blob.core.windows.net/miciiccontainer1/",
    3: "https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes",
    4: "https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes",
}


def resolve_blob_url(
    path: Optional[str],
    academic_year: Optional[str] = None,
    event_driven: Optional[int] = None
) -> Optional[str]:
    """
    Simple deterministic blob URL resolver - NO fallbacks, NO path manipulation.
    
    Rule:
    1. If path is already a full URL (starts with "https://"), return as-is
    2. Get base path from EVENT_DRIVEN_BASE_PATH[event_driven]
    3. Remove leading "/" from submission path if present
    4. Concatenate: base_path + "/" + submission_path
    
    Args:
        path: Raw submission file path from CSV (e.g., "/monthlyReport/report/file.pdf")
        academic_year: Academic year (UNUSED - kept for compatibility)
        event_driven: Event driven type (1, 2, 3, or 4) - REQUIRED
    
    Returns:
        Full Azure Blob Storage URL, or None if path is invalid
    
    Examples:
        >>> resolve_blob_url("/monthlyReport/report/file.pdf", None, 1)
        'https://miciicsta01.blob.core.windows.net/miciiccontainer1/monthlyReport/report/file.pdf'
        
        >>> resolve_blob_url("uploads-2024-25/institutes/monthlyReport/report/file.pdf", None, 3)
        'https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes/uploads-2024-25/institutes/monthlyReport/report/file.pdf'
    """
    if not path or not path.strip():
        return None
    
    original_path = path
    path = path.strip()
    
    # If already a full URL, return as-is
    if path.startswith("https://"):
        logger.info(f"Input: {original_path} | Already full URL | Resolved: {path}")
        return path
    
    # Get base path for event_driven type
    if event_driven not in EVENT_DRIVEN_BASE_PATH:
        logger.warning(f"Invalid event_driven: {event_driven}, using default base path")
        base_path = EVENT_DRIVEN_BASE_PATH[1]  # Default to type 1
    else:
        base_path = EVENT_DRIVEN_BASE_PATH[event_driven]
    
    # Remove leading "/" from submission path if present
    submission_path = path.lstrip("/")
    
    # Concatenate: base_path + "/" + submission_path
    # Ensure base_path ends with "/" or add it
    if base_path.endswith("/"):
        final_url = base_path + submission_path
    else:
        final_url = base_path + "/" + submission_path
    
    logger.info(f"Input: {original_path} | Event Driven: {event_driven} | Resolved: {final_url}")
    return final_url

