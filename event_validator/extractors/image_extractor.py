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
            
            # OPTIMIZATION: Smart Resize
            # Resize if significantly larger than needed (e.g. > 1920px)
            # 1920px is sufficient for Gemini Vision but faster to upload
            max_dimension = 1920
            if max(img.size) > max_dimension:
                # Calculate new size preserving aspect ratio
                ratio = max_dimension / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                logger.debug(f"  Resizing image {image_path.name} from {img.size} to {new_size} for optimization")
                
                # EXTRACT EXIF BEFORE SAVING/RESIZING to allow metadata preservation
                exif = img._getexif()
                if exif:
                     for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        exif_data[tag] = value
                        if tag == 'GPSInfo':
                            has_geotag = True
                            gps_info = {}
                            for gps_tag_id, gps_value in value.items():
                                gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                                gps_info[gps_tag] = gps_value
                            exif_data['GPSDetails'] = gps_info
                
                # Use LANCZOS for best quality downsampling
                img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # Overwrite file with optimized version
                img_resized.save(image_path, quality=95, optimize=True)
                
                # Re-open for any subsequent processing if needed
                img = img_resized
            else:
                # No resize needed, just extract EXIF
                exif = img._getexif()
                if exif:
                     for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        exif_data[tag] = value
                        if tag == 'GPSInfo':
                            has_geotag = True
                            gps_info = {}
                            for gps_tag_id, gps_value in value.items():
                                gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                                gps_info[gps_tag] = gps_value
                            exif_data['GPSDetails'] = gps_info

            if has_geotag:
                 logger.debug(f"Geotag found in {image_path.name}: GPSInfo present")
            else:
                logger.debug(f"No EXIF geotag found in {image_path.name}")
                
            # Additional check: Try alternative methods to detect GPS data (e.g. XMP/Info)
            try:
                if hasattr(img, 'info'):
                    info = img.info
                    if any('gps' in str(k).lower() or 'location' in str(k).lower() for k in info.keys()):
                        has_geotag = True
                        logger.debug(f"Geotag found in {image_path.name} via info dict")
            except Exception as e:
                logger.debug(f"Could not check info dict: {e}")
                
        except Exception as e:
            logger.warning(f"Error processing image {image_path}: {e}")
    
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
