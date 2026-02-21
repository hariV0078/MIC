"""
OCR Utility using EasyOCR.
Used for robust visual geotag detection ("GPS Map Camera" overlays) where LLMs might fail.
"""
import logging
import threading
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Global reader instance (lazy loaded)
_reader = None
_reader_lock = threading.Lock()

def get_reader():
    """Get or initialize the EasyOCR reader singleton (thread-safe)."""
    global _reader
    with _reader_lock:
        if _reader is not None:
            return _reader
        
        try:
            import easyocr
            # Initialize reader with English model
            # gpu=False to save VRAM for Ollama (since user mentioned limits)
            # verbose=False to reduce noise
            print("⏳ Loading EasyOCR reader for the first time (CPU mode)...")
            _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            return _reader
        except ImportError:
            print("❌ ERROR: EasyOCR is not installed. Run: pip install easyocr")
            return None
        except Exception as e:
            print(f"❌ ERROR: EasyOCR failed to load. Reason: {e}")
            return None

def extract_visual_geotag(image_path: str) -> Tuple[bool, str]:
    """
    Check for visual geotags using EasyOCR.
    Returns: (has_geotag, extracted_text)
    """
    reader = get_reader()
    if not reader:
        return False, ""
    
    try:
        # detail=0 returns just the text list
        result = reader.readtext(str(image_path), detail=0)
        full_text = " ".join(result).lower()
        
        # Keywords to detect "GPS Map Camera" or coordinates
        if "gps map camera" in full_text:
            logger.info(f"EasyOCR: Found 'GPS Map Camera' in {image_path}")
            return True, full_text
            
        if "lat" in full_text and "long" in full_text:
            logger.info(f"EasyOCR: Found 'Lat/Long' in {image_path}")
            return True, full_text
            
        # Optional: Check for "Address" or "Location" if user wants strictness
        # sticking to user request for now
        
        return False, full_text
    except Exception as e:
        print(f"❌ EasyOCR error on {image_path}: {e}")
        return False, ""
