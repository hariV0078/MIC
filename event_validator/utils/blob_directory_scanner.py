"""Azure Blob Storage directory scanner for duplicate detection."""
import logging
import requests
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from io import BytesIO
import xml.etree.ElementTree as ET

from event_validator.utils.blob_path_resolver import EVENT_DRIVEN_BASE_PATH
from event_validator.utils.hashing import compute_sha256, compute_phash, hamming_distance

logger = logging.getLogger(__name__)

BLOB_ROOT = "https://miciicsta01.blob.core.windows.net/miciiccontainer1/"


def get_base_path(event_driven: Optional[int]) -> str:
    """Get base path for event_driven type."""
    if event_driven in EVENT_DRIVEN_BASE_PATH:
        return EVENT_DRIVEN_BASE_PATH[event_driven]
    return EVENT_DRIVEN_BASE_PATH[1]  # Default to type 1


# Global cache for directory file hashes (lazy-loaded)
_directory_hash_cache: Dict[str, Dict[str, Dict]] = {}


class BlobDirectoryScanner:
    """Scans Azure Blob Storage directories for duplicate detection."""
    
    def __init__(self, phash_threshold: int = 5):
        """
        Initialize directory scanner.
        
        Args:
            phash_threshold: Hamming distance threshold for near-duplicate detection
        """
        self.phash_threshold = phash_threshold
        self._cache = {}  # Cache: {directory_path: {sha256: file_info}}
    
    def _list_blobs_in_directory(
        self,
        directory_path: str,
        event_driven: Optional[int] = None,
        academic_year: Optional[str] = None
    ) -> List[str]:
        """
        List blob URLs in a directory using Azure Blob Storage REST API.
        
        Note: This requires the container to allow public list access or use SAS tokens.
        For now, we'll use a simplified approach that tries to enumerate common patterns.
        
        Args:
            directory_path: Directory path to scan (e.g., "monthlyReport/Photograph1/")
            event_driven: Event driven type
            academic_year: Academic year
        
        Returns:
            List of blob URLs
        """
        # Construct base URL for directory
        base_path = get_base_path(event_driven)
        
        if academic_year:
            if event_driven in (3, 4):
                base_url = f"{BLOB_ROOT}uploads-{academic_year}/institutes/{directory_path}"
            else:
                base_url = f"{BLOB_ROOT}uploads-{academic_year}/{directory_path}"
        else:
            base_url = f"{base_path}/{directory_path}" if not base_path.endswith("/") else f"{base_path}{directory_path}"
        
        # Azure Blob Storage REST API: List Blobs
        # Note: This requires public read access or SAS token
        # For now, we'll return empty list and rely on batch-level detection
        # In production, implement proper Azure SDK or REST API calls
        
        logger.warning(
            f"Directory enumeration not fully implemented. "
            f"Base URL would be: {base_url}. "
            f"Using batch-level duplicate detection as fallback."
        )
        
        return []
    
    def scan_directory_for_duplicates(
        self,
        target_sha256: str,
        target_phash: Optional[str],
        event_driven: Optional[int],
        academic_year: Optional[str],
        submission_id: str
    ) -> List[Tuple[str, str, Optional[float]]]:
        """
        Scan directory for duplicates of target file.
        
        Args:
            target_sha256: SHA256 hash of target file
            target_phash: Perceptual hash of target file (optional)
            event_driven: Event driven type
            academic_year: Academic year
            submission_id: Current submission ID
        
        Returns:
            List of (matched_file_path, match_type, similarity_score) tuples
            match_type: 'exact' (SHA256) or 'near-duplicate' (pHash)
            similarity_score: Hamming distance for near-duplicates, None for exact
        """
        # For now, use batch-level detection as primary method
        # Directory scanning requires Azure SDK or public list access
        
        # Cache key for this directory
        cache_key = f"{event_driven}_{academic_year}"
        
        # Check cache first
        if cache_key in _directory_hash_cache:
            cached_files = _directory_hash_cache[cache_key]
            
            # Check for exact match
            if target_sha256 in cached_files:
                file_info = cached_files[target_sha256]
                return [(
                    file_info.get('path', 'unknown'),
                    'exact',
                    None
                )]
            
            # Check for near-duplicate (pHash)
            if target_phash:
                for cached_sha256, cached_info in cached_files.items():
                    cached_phash = cached_info.get('phash')
                    if cached_phash:
                        distance = hamming_distance(target_phash, cached_phash)
                        if distance <= self.phash_threshold:
                            return [(
                                cached_info.get('path', 'unknown'),
                                'near-duplicate',
                                float(distance)
                            )]
        
        # No matches found
        return []
    
    def add_file_to_cache(
        self,
        sha256: str,
        phash: Optional[str],
        file_path: str,
        event_driven: Optional[int],
        academic_year: Optional[str],
        submission_id: str
    ):
        """
        Add file hash to directory cache.
        
        Args:
            sha256: SHA256 hash
            phash: Perceptual hash
            file_path: File path/URL
            event_driven: Event driven type
            academic_year: Academic year
            submission_id: Submission ID
        """
        cache_key = f"{event_driven}_{academic_year}"
        
        if cache_key not in _directory_hash_cache:
            _directory_hash_cache[cache_key] = {}
        
        _directory_hash_cache[cache_key][sha256] = {
            'phash': phash,
            'path': file_path,
            'submission_id': submission_id,
            'first_seen': submission_id  # Track first submission that saw this file
        }
    
    def clear_cache(self, event_driven: Optional[int] = None, academic_year: Optional[str] = None):
        """Clear directory hash cache."""
        global _directory_hash_cache
        
        if event_driven is not None and academic_year:
            cache_key = f"{event_driven}_{academic_year}"
            if cache_key in _directory_hash_cache:
                del _directory_hash_cache[cache_key]
        else:
            _directory_hash_cache.clear()


def get_directory_scanner(phash_threshold: int = 5) -> BlobDirectoryScanner:
    """Get or create directory scanner instance."""
    return BlobDirectoryScanner(phash_threshold=phash_threshold)

