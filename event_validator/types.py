"""Type definitions for the event validation system."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path


@dataclass
class ValidationResult:
    """Result of a single validation criterion."""
    criterion: str
    passed: bool
    points_awarded: int
    message: str


@dataclass
class PDFData:
    """Extracted PDF data."""
    text: str
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ImageData:
    """Extracted image data."""
    path: Path
    sha256: Optional[str] = None
    phash: Optional[str] = None
    exif_data: Optional[Dict[str, Any]] = None
    has_geotag: bool = False


@dataclass
class EventSubmission:
    """Represents a single event submission from CSV."""
    # CSV row data (mapped to standard format)
    row_data: Dict[str, Any]
    
    # Extracted data
    pdf_data: Optional[PDFData] = None
    images: Optional[List[ImageData]] = None
    
    # Validation results
    validation_results: Optional[List[ValidationResult]] = None
    overall_score: int = 0
    status: str = "Rejected"
    requirements_not_met: str = ""


@dataclass
class ValidationConfig:
    """Configuration for validation rules."""
    acceptance_threshold: int = 75
    duplicate_phash_threshold: int = 5  # Hamming distance threshold for pHash
    base_image_path: Optional[Path] = None
    groq_api_key: Optional[str] = None

