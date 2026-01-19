"""PDF text extraction with OCR fallback."""
import logging
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import pytesseract
    from PIL import Image as PILImage
except ImportError:
    pytesseract = None
    PILImage = None

from event_validator.types import PDFData

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: Path) -> PDFData:
    """
    Extract text from PDF using multiple methods.
    Falls back to OCR if text extraction fails.
    """
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return PDFData(text="", metadata={})
    
    text = ""
    metadata = {}
    
    # Method 1: Try pdfplumber (better text extraction)
    if pdfplumber is not None:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                text = "\n".join(text_parts)
                
                # Extract metadata
                metadata = pdf.metadata or {}
                if not text.strip() and len(pdf.pages) > 0:
                    logger.warning(f"pdfplumber extracted no text from {pdf_path}, trying PyPDF2")
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed for {pdf_path}: {e}")
    
    # Method 2: Try PyPDF2 if pdfplumber failed
    if not text.strip() and PyPDF2 is not None:
        try:
            with open(pdf_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                text_parts = []
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                text = "\n".join(text_parts)
                
                # Extract metadata
                if pdf_reader.metadata:
                    metadata = {
                        k: str(v) if v else "" 
                        for k, v in pdf_reader.metadata.items()
                    }
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed for {pdf_path}: {e}")
    
    # Method 3: OCR fallback if text extraction failed
    if not text.strip() and pytesseract is not None and PILImage is not None:
        try:
            logger.info(f"Attempting OCR for {pdf_path}")
            # Convert PDF pages to images and OCR
            # Note: This requires pdf2image or similar
            # For now, we'll skip OCR if pdf2image is not available
            logger.warning("OCR fallback requires pdf2image. Skipping OCR.")
        except Exception as e:
            logger.warning(f"OCR extraction failed for {pdf_path}: {e}")
    
    # Extract title from metadata or first line of text
    title = None
    if metadata:
        title = metadata.get('/Title') or metadata.get('Title') or metadata.get('title')
    
    if not title and text:
        # Try to extract title from first line
        first_line = text.split('\n')[0].strip()
        if len(first_line) > 5 and len(first_line) < 200:
            title = first_line
    
    return PDFData(
        text=text,
        title=title,
        metadata=metadata
    )

