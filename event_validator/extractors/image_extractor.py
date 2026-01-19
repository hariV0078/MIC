"""Image metadata and hash extraction."""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
except ImportError:
    Image = None
    TAGS = None
    GPSTAGS = None

from event_validator.types import ImageData
from event_validator.utils.hashing import compute_sha256, compute_phash

logger = logging.getLogger(__name__)


def extract_image_metadata(image_path: Path) -> ImageData:
    """Extract metadata, hashes, and geotag info from an image."""
    sha256_hash = compute_sha256(image_path)
    phash_value = compute_phash(image_path)
    
    exif_data = {}
    has_geotag = False
    
    if Image is not None:
        try:
            img = Image.open(image_path)
            exif = img._getexif()
            
            if exif is not None:
                # Extract EXIF data
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    exif_data[tag] = value
                    
                    # Check for GPS data (geotag)
                    if tag == 'GPSInfo':
                        has_geotag = True
                        # Extract GPS details
                        gps_info = {}
                        for gps_tag_id, gps_value in value.items():
                            gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                            gps_info[gps_tag] = gps_value
                        exif_data['GPSDetails'] = gps_info
        except Exception as e:
            logger.warning(f"Error extracting EXIF from {image_path}: {e}")
    
    return ImageData(
        path=image_path,
        sha256=sha256_hash,
        phash=phash_value,
        exif_data=exif_data,
        has_geotag=has_geotag
    )


def extract_images_from_paths(image_paths: List[Path]) -> List[ImageData]:
    """Extract metadata from multiple image files."""
    images = []
    for img_path in image_paths:
        if img_path.exists():
            try:
                img_data = extract_image_metadata(img_path)
                images.append(img_data)
            except Exception as e:
                logger.error(f"Error processing image {img_path}: {e}")
        else:
            logger.warning(f"Image file not found: {img_path}")
    
    return images

