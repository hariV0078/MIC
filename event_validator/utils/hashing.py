"""Hashing utilities for duplicate detection."""
import hashlib
import io
from pathlib import Path
from typing import Optional, Union, List, Tuple
import logging

try:
    from PIL import Image
    import imagehash
except ImportError:
    Image = None
    imagehash = None

logger = logging.getLogger(__name__)


def compute_sha256(file_path: Union[Path, io.BytesIO]) -> Optional[str]:
    """Compute SHA256 hash of a file or stream."""
    try:
        hash_sha256 = hashlib.sha256()
        
        if isinstance(file_path, io.BytesIO):
            # Reset stream position
            file_path.seek(0)
            for chunk in iter(lambda: file_path.read(4096), b""):
                if not chunk:
                    break
                hash_sha256.update(chunk)
            file_path.seek(0)  # Reset for potential reuse
        else:
            # File path
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
        
        return hash_sha256.hexdigest()
    except Exception as e:
        logger.error(f"Error computing SHA256: {e}")
        return None


def compute_phash(file_path: Union[Path, io.BytesIO]) -> Optional[str]:
    """Compute perceptual hash (pHash) of an image from file or stream."""
    if Image is None or imagehash is None:
        logger.warning("PIL/imagehash not available. Install with: pip install pillow imagehash")
        return None
    
    try:
        if isinstance(file_path, io.BytesIO):
            file_path.seek(0)
            img = Image.open(file_path)
            file_path.seek(0)  # Reset for potential reuse
        else:
            img = Image.open(file_path)
        
        phash = imagehash.phash(img)
        return str(phash)
    except Exception as e:
        logger.error(f"Error computing pHash: {e}")
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculate Hamming distance between two hashes."""
    if len(hash1) != len(hash2):
        return float('inf')
    
    return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))


def find_duplicates_in_directory(
    target_hash: str,
    target_phash: Optional[str],
    base_directory: Path,
    phash_threshold: int = 5
) -> List[Tuple[Path, str]]:
    """
    Find duplicate images in base directory.
    
    Returns list of (matched_file_path, match_type) tuples.
    Match types: 'exact' (SHA256) or 'similar' (pHash).
    """
    matches = []
    
    if not base_directory.exists():
        return matches
    
    # Supported image extensions
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    
    try:
        for file_path in base_directory.rglob('*'):
            if file_path.suffix.lower() not in image_extensions:
                continue
            
            # Check exact match (SHA256)
            file_hash = compute_sha256(file_path)
            if file_hash and file_hash == target_hash:
                matches.append((file_path, 'exact'))
                continue
            
            # Check similar match (pHash) if available
            if target_phash:
                file_phash = compute_phash(file_path)
                if file_phash:
                    distance = hamming_distance(target_phash, file_phash)
                    if distance <= phash_threshold:
                        matches.append((file_path, 'similar'))
    
    except Exception as e:
        logger.error(f"Error scanning directory {base_directory}: {e}")
    
    return matches

