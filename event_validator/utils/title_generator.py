"""Event-driven title generation and validation logic."""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def generate_canonical_title(
    event_type: Optional[str],
    theme: Optional[str],
    objectives: Optional[str],
    learning_outcomes: Optional[str]
) -> str:
    """
    Generate canonical title for event_driven types 1, 2, 4.
    
    For event_driven 3, users provide titles directly.
    For 1, 2, 4, system generates canonical titles from event metadata.
    
    Args:
        event_type: Event type (e.g., "Level 1 - Expert Talk")
        theme: Event theme
        objectives: Event objectives
        learning_outcomes: Learning outcomes
    
    Returns:
        Canonical title string
    """
    # Extract level from event_type if present
    level = None
    event_type_clean = event_type or ""
    
    if "Level" in event_type_clean:
        try:
            level_part = event_type_clean.split("Level")[1].strip().split()[0]
            level = f"Level {level_part}"
        except (IndexError, ValueError):
            pass
    
    # Build canonical title
    parts = []
    
    if level:
        parts.append(level)
    
    # Extract event category from event_type
    if "-" in event_type_clean:
        category = event_type_clean.split("-", 1)[1].strip()
        parts.append(category)
    else:
        parts.append(event_type_clean)
    
    if theme:
        parts.append(f"on {theme}")
    
    # Construct title
    canonical_title = " - ".join(parts) if len(parts) > 1 else parts[0] if parts else "Event"
    
    logger.debug(f"Generated canonical title: {canonical_title}")
    return canonical_title


def should_validate_against_canonical_title(event_driven: Optional[int]) -> bool:
    """
    Determine if title should be validated against canonical title.
    
    Args:
        event_driven: Event driven type
    
    Returns:
        True if should use canonical title (1, 2, 4), False if user-provided (3)
    """
    return event_driven in (1, 2, 4)


def get_expected_title(
    event_driven: Optional[int],
    user_title: Optional[str],
    event_type: Optional[str],
    theme: Optional[str],
    objectives: Optional[str],
    learning_outcomes: Optional[str]
) -> str:
    """
    Get expected title based on event_driven policy.
    
    Args:
        event_driven: Event driven type
        user_title: User-provided title (from CSV)
        event_type: Event type
        theme: Event theme
        objectives: Objectives
        learning_outcomes: Learning outcomes
    
    Returns:
        Expected title for validation
    """
    if should_validate_against_canonical_title(event_driven):
        # Generate canonical title for event_driven 1, 2, 4
        return generate_canonical_title(
            event_type=event_type,
            theme=theme,
            objectives=objectives,
            learning_outcomes=learning_outcomes
        )
    else:
        # For event_driven 3, use user-provided title
        return user_title or ""


def format_title_validation_message(
    event_driven: Optional[int],
    expected_title: str,
    observed_title: Optional[str],
    reason: str
) -> str:
    """
    Format audit-ready title validation failure message.
    
    Args:
        event_driven: Event driven type
        expected_title: Expected title
        observed_title: Observed title
        reason: Failure reason
    
    Returns:
        Formatted message
    """
    if should_validate_against_canonical_title(event_driven):
        return (
            f"Content does not match canonical event title. "
            f"Expected: \"{expected_title}\". "
            f"Observed: \"{observed_title or 'Not provided'}\". "
            f"Reason: {reason}"
        )
    else:
        return (
            f"Title/Objectives/Learning do not align with theme: {expected_title}. "
            f"Observed: \"{observed_title or 'Not provided'}\". "
            f"Reason: {reason}"
        )

