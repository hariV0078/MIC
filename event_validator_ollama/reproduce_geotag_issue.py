
import os
import sys
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from event_validator.validators.image_validator import validate_images
from event_validator.validators.ollama_client import OllamaClient
from event_validator.types import EventSubmission, ImageData

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_test_images():
    """Create two test images: one plain, one with visual geotag."""
    
    # Image 1: Plain (No Geotag)
    img1_path = Path("test_img1.jpg")
    img1 = Image.new('RGB', (800, 600), color = (73, 109, 137))
    d1 = ImageDraw.Draw(img1)
    d1.text((10,10), "Image 1: No Geotag", fill=(255, 255, 0))
    img1.save(img1_path)
    
    # Image 2: Visual Geotag
    img2_path = Path("test_img2.jpg")
    img2 = Image.new('RGB', (800, 600), color = (200, 100, 100))
    d2 = ImageDraw.Draw(img2)
    
    # Draw text large enough to be read even if resized slightly, 
    # but the resizing to 448x448 might still degrade it.
    text = "Location details:\nLat: 28.6139\nLong: 77.2090\nDate: 15-08-2025"
    d2.text((50, 50), text, fill=(255, 255, 255))
    img2.save(img2_path)
    
    return img1_path, img2_path

def test_geotag_loop():
    logger.info("Creating test images...")
    p1, p2 = create_test_images()
    
    # Mock submission with 2 images
    submission = EventSubmission(
        row_data={
            "Title": "Test Event",
            "Theme": "Innovation",
            "Event Mode": "Offline"
        }
    )
    
    # Create ImageData objects
    # Note: We are NOT extracting metadata here to simulate missing EXIF
    # so has_geotag=False for both.
    submission.images = [
        ImageData(path=p1, sha256="1", phash="1", exif_data={}, has_geotag=False),
        ImageData(path=p2, sha256="2", phash="2", exif_data={}, has_geotag=False)
    ]
    
    logger.info("Initializing Ollama Client...")
    # Ensure you have Ollama running! 
    # If not, this test will fail on connection, but for logic check we assume it's up.
    client = OllamaClient()
    
    if not client.client:
        logger.error("Ollama client not verified. Skipping live inference test.")
        return

    logger.info("Running validate_images...")
    results = validate_images(submission, client)
    
    # Check Geotag Result
    geotag_result = next((r for r in results if "Geotag" in r.criterion), None)
    
    if not geotag_result:
        logger.error("Geotag validation result not found!")
        return

    logger.info(f"Geotag Result: {geotag_result.passed} - {geotag_result.message}")
    
    if geotag_result.passed:
        logger.info("SUCCESS: Geotag detected in second image!")
    else:
        logger.error("FAILURE: Geotag NOT detected (Loop logic failed or OCR failed).")

    # Cleanup
    if p1.exists(): os.remove(p1)
    if p2.exists(): os.remove(p2)

if __name__ == "__main__":
    test_geotag_loop()
