"""Column mapping utilities for CSV/XLSX data."""
from typing import Dict, Any, Optional
import logging

from event_validator.utils.blob_path_resolver import resolve_blob_url

logger = logging.getLogger(__name__)


# Level definitions based on event type and duration
LEVEL_DEFINITIONS = {
    1: {
        "event_types": ["Expert Talk", "Mentoring Session", "Exposure Visit"],
        "duration_range": (2, 4),  # 2 to 4 contact hours
        "description": "Less than half a day"
    },
    2: {
        "event_types": [
            "Seminar", "Workshop", "Conference", "Exposure Visit",
            "Panel Discussion", "Roundtable Discussion", "Networking Event"
        ],
        "duration_range": (5, 8),  # 5 to 8 contact hours
        "description": "One Full day"
    },
    3: {
        "event_types": [
            "Boot Camp", "Workshop", "Exhibition/ Startup Showcase",
            "Demo Day", "Competition", "Hackathons", "Conference"
        ],
        "duration_range": (9, 18),  # 9 to 18 contact hours
        "description": "More than one day"
    },
    4: {
        "event_types": [
            "Challenge", "Tech/ E-Fest", "Hackathon", "Competition",
            "Workshop", "Boot Camp", "Exhibition/ Startup Showcase"
        ],
        "duration_range": (19, float('inf')),  # Greater than 18 contact hours
        "description": "More than 2 days"
    }
}


def map_row_to_standard_format(row_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map actual CSV columns to standard validation format.
    
    Maps:
    - activity_name -> Title
    - Objective -> Objectives
    - benefit_learning -> Learning Outcomes
    - event_theme -> Theme
    - event_type -> Event Type
    - activity_duration -> Duration (in hours)
    - student_participants + faculty_participants -> Participants
    - from_date -> Event Date
    - financial_year -> Year Type
    - session_type -> Event Mode
    - report -> PDF Path (with Azure Blob Storage base path)
    - photo1, photo2 -> Image Paths (with Azure Blob Storage base path)
    - event_driven -> Event Driven (for path resolution)
    """
    mapped = {}
    
    # Basic mappings
    mapped['Title'] = str(row_data.get('activity_name', '')).strip()
    mapped['Objectives'] = str(row_data.get('Objective', '')).strip()
    mapped['Learning Outcomes'] = str(row_data.get('benefit_learning', '')).strip()
    mapped['Theme'] = str(row_data.get('event_theme', '')).strip()
    mapped['Event Type'] = str(row_data.get('event_type', '')).strip()
    mapped['Event Date'] = str(row_data.get('from_date', '')).strip()
    mapped['Year Type'] = str(row_data.get('financial_year', 'Financial')).strip()
    mapped['Event Mode'] = str(row_data.get('session_type', '')).strip()
    
    # Duration mapping (activity_duration is in hours)
    activity_duration = row_data.get('activity_duration')
    if activity_duration is not None:
        try:
            duration_hours = float(activity_duration)
            mapped['Duration'] = f"{duration_hours}h"
        except (ValueError, TypeError):
            mapped['Duration'] = str(activity_duration) if activity_duration else ""
    else:
        mapped['Duration'] = ""
    
    # Participants: sum of student and faculty
    student_participants = row_data.get('student_participants', 0) or 0
    faculty_participants = row_data.get('faculty_participants', 0) or 0
    try:
        total_participants = int(student_participants) + int(faculty_participants)
        mapped['Participants'] = str(total_participants)
    except (ValueError, TypeError):
        mapped['Participants'] = "0"
    
    # Level determination
    level = determine_level(
        event_type=mapped.get('Event Type', ''),
        duration_hours=activity_duration
    )
    mapped['Level'] = str(level) if level else ""
    
    # Get academic year for URL construction (try acadmic_year first, then financial_year)
    academic_year = row_data.get('acadmic_year') or row_data.get('financial_year', '')
    academic_year = str(academic_year).strip()
    
    # Normalize academic year format to "YYYY-YY" (e.g., "2024-25")
    if academic_year:
        if '-' in academic_year:
            # Handle formats like "2024-25" or "2024-2025"
            parts = academic_year.split('-')
            if len(parts) == 2 and len(parts[0]) == 4:
                if len(parts[1]) == 4:
                    # Convert "2024-2025" to "2024-25"
                    academic_year = f"{parts[0]}-{parts[1][-2:]}"
                elif len(parts[1]) == 2:
                    # Already in "2024-25" format
                    pass  # Keep as-is
                else:
                    # Invalid format, try to extract
                    academic_year = ""
        elif len(academic_year) >= 4:
            # Convert "2024" or "202425" to "2024-25" format
            try:
                year_start = int(academic_year[:4])
                year_end = str(year_start + 1)[-2:]  # Last 2 digits of next year
                academic_year = f"{year_start}-{year_end}"
            except (ValueError, IndexError):
                academic_year = ""  # Invalid format, will use fallback
    else:
        academic_year = ""
    
    # Get event_driven for path resolution
    event_driven = row_data.get('event_driven')
    try:
        event_driven = int(event_driven) if event_driven is not None else None
    except (ValueError, TypeError):
        event_driven = None
    
    # Azure Blob Storage URL construction using smart path resolver
    # PDF Path
    report_path = str(row_data.get('report', '')).strip()
    if report_path:
        mapped['PDF Path'] = resolve_blob_url(report_path, academic_year, event_driven) or ""
    else:
        mapped['PDF Path'] = ""
    
    # Image Paths
    photo1 = str(row_data.get('photo1', '')).strip()
    photo2 = str(row_data.get('photo2', '')).strip()
    image_paths = []
    
    # Skip invalid paths (empty, "0", or just whitespace)
    invalid_paths = {'', '0', 'null', 'none', 'n/a'}
    
    if photo1 and photo1.lower() not in invalid_paths:
        resolved_url = resolve_blob_url(photo1, academic_year, event_driven)
        if resolved_url:
            image_paths.append(resolved_url)
    
    if photo2 and photo2.lower() not in invalid_paths:
        resolved_url = resolve_blob_url(photo2, academic_year, event_driven)
        if resolved_url:
            image_paths.append(resolved_url)
    
    mapped['Image Paths'] = ",".join(image_paths) if image_paths else ""
    
    # Keep original data for reference
    mapped['_original_data'] = row_data
    
    return mapped


def determine_level(event_type: str, duration_hours: Optional[float]) -> Optional[int]:
    """
    Determine level based on event type and duration.
    
    Returns level (1-4) or None if cannot be determined.
    """
    if not event_type or duration_hours is None:
        return None
    
    event_type = event_type.strip()
    
    # Try to determine level from event type first
    for level, definition in LEVEL_DEFINITIONS.items():
        if event_type in definition["event_types"]:
            min_hours, max_hours = definition["duration_range"]
            if min_hours <= duration_hours <= max_hours:
                return level
    
    # If event type doesn't match, determine by duration only
    if 2 <= duration_hours <= 4:
        return 1
    elif 5 <= duration_hours <= 8:
        return 2
    elif 9 <= duration_hours <= 18:
        return 3
    elif duration_hours > 18:
        return 4
    
    return None




def validate_level_duration_match(level: int, duration_hours: float) -> bool:
    """
    Validate if level matches duration according to LEVEL_DEFINITIONS.
    
    Returns True if level and duration match, False otherwise.
    """
    if level not in LEVEL_DEFINITIONS:
        return False
    
    definition = LEVEL_DEFINITIONS[level]
    min_hours, max_hours = definition["duration_range"]
    
    return min_hours <= duration_hours <= max_hours

