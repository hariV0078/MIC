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
            import os
            
            # Check for explicit GPU disabling via environment variable
            use_gpu = os.getenv("USE_GPU", "1") != "0"
            
            # Auto-detect CUDA availability if GPU is requested
            if use_gpu:
                try:
                    import torch
                    if not torch.cuda.is_available():
                        logger.warning("GPU requested but CUDA is not available. Falling back to CPU.")
                        use_gpu = False
                except ImportError:
                    logger.warning("GPU requested but torch not found. Falling back to CPU.")
                    use_gpu = False
            
            # Initialize reader
            if use_gpu:
                logger.info("⏳ Loading EasyOCR reader (GPU mode)...")
            else:
                logger.info("⏳ Loading EasyOCR reader (CPU mode)...")
                
            try:
                _reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
                return _reader
            except Exception as e:
                if use_gpu:
                    logger.warning(f"EasyOCR failed to load in GPU mode: {e}. Falling back to CPU...")
                    _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                    return _reader
                else:
                    raise e
                    
        except ImportError:
            logger.error("❌ ERROR: EasyOCR is not installed. Run: pip install easyocr")
            return None
        except Exception as e:
            logger.error(f"❌ ERROR: EasyOCR failed to load. Reason: {e}")
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
            
        return False, full_text
    except Exception as e:
        print(f"❌ EasyOCR error on {image_path}: {e}")
        return False, ""
