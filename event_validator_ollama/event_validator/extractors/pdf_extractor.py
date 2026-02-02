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

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

from event_validator.types import PDFData

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: Path) -> PDFData:
    """
    Extract text from PDF using multiple methods with improved error handling.
    Falls back to OCR if text extraction fails.
    """
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return PDFData(text="", metadata={})
    
    text = ""
    metadata = {}
    extraction_method = "none"
    
    # Method 1: Try pdfplumber (better text extraction, handles more PDF formats)
    if pdfplumber is not None:
        try:
            logger.debug(f"Attempting pdfplumber extraction for {pdf_path.name}")
            with pdfplumber.open(pdf_path) as pdf:
                text_parts = []
                total_pages = len(pdf.pages)
                logger.debug(f"PDF has {total_pages} pages")
                
                for i, page in enumerate(pdf.pages, 1):
                    try:
                        # Try standard text extraction
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_parts.append(page_text.strip())
                        else:
                            # Try alternative extraction method for this page
                            # Some PDFs have text in tables or other structures
                            try:
                                # Try extracting from tables
                                tables = page.extract_tables()
                                if tables:
                                    for table in tables:
                                        for row in table:
                                            if row:
                                                row_text = " ".join([str(cell) if cell else "" for cell in row])
                                                if row_text.strip():
                                                    text_parts.append(row_text.strip())
                            except Exception as table_e:
                                logger.debug(f"Table extraction failed for page {i}: {table_e}")
                            
                            # Try extracting text with layout preservation
                            try:
                                page_text_layout = page.extract_text(layout=True)
                                if page_text_layout and page_text_layout.strip():
                                    text_parts.append(page_text_layout.strip())
                            except Exception as layout_e:
                                logger.debug(f"Layout extraction failed for page {i}: {layout_e}")
                    
                    except Exception as page_e:
                        logger.warning(f"Error extracting text from page {i} of {pdf_path.name}: {page_e}")
                        continue
                
                text = "\n".join(text_parts)
                
                # Extract metadata
                try:
                    metadata = pdf.metadata or {}
                except Exception as meta_e:
                    logger.debug(f"Could not extract metadata: {meta_e}")
                    metadata = {}
                
                if text.strip():
                    extraction_method = "pdfplumber"
                    logger.info(f"Successfully extracted {len(text)} characters from {pdf_path.name} using pdfplumber")
                elif total_pages > 0:
                    logger.warning(f"pdfplumber extracted no text from {pdf_path.name} ({total_pages} pages), trying PyPDF2")
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed for {pdf_path.name}: {e}")
    
    # Method 2: Try PyPDF2 if pdfplumber failed or extracted no text
    if not text.strip() and PyPDF2 is not None:
        try:
            logger.debug(f"Attempting PyPDF2 extraction for {pdf_path.name}")
            with open(pdf_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                text_parts = []
                total_pages = len(pdf_reader.pages)
                logger.debug(f"PDF has {total_pages} pages (PyPDF2)")
                
                for i, page in enumerate(pdf_reader.pages, 1):
                    try:
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_parts.append(page_text.strip())
                    except Exception as page_e:
                        logger.warning(f"Error extracting text from page {i} using PyPDF2: {page_e}")
                        continue
                
                text = "\n".join(text_parts)
                
                # Extract metadata
                try:
                    if pdf_reader.metadata:
                        metadata = {
                            k: str(v) if v else "" 
                            for k, v in pdf_reader.metadata.items()
                        }
                except Exception as meta_e:
                    logger.debug(f"Could not extract metadata from PyPDF2: {meta_e}")
                    metadata = {}
                
                if text.strip():
                    extraction_method = "PyPDF2"
                    logger.info(f"Successfully extracted {len(text)} characters from {pdf_path.name} using PyPDF2")
                else:
                    logger.warning(f"PyPDF2 extracted no text from {pdf_path.name}")
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed for {pdf_path.name}: {e}")
    
    # Method 3: OCR fallback if text extraction failed
    if not text.strip() and PDF2IMAGE_AVAILABLE and pytesseract is not None and PILImage is not None:
        try:
            logger.info(f"Attempting OCR for {pdf_path.name} (text extraction failed)")
            # Convert PDF pages to images and OCR
            images = convert_from_path(str(pdf_path), dpi=300)
            ocr_text_parts = []
            
            for i, image in enumerate(images, 1):
                try:
                    ocr_text = pytesseract.image_to_string(image, lang='eng')
                    if ocr_text and ocr_text.strip():
                        ocr_text_parts.append(ocr_text.strip())
                        logger.debug(f"OCR extracted text from page {i}")
                except Exception as ocr_e:
                    logger.warning(f"OCR failed for page {i}: {ocr_e}")
                    continue
            
            if ocr_text_parts:
                text = "\n".join(ocr_text_parts)
                extraction_method = "OCR"
                logger.info(f"Successfully extracted {len(text)} characters from {pdf_path.name} using OCR")
            else:
                logger.warning(f"OCR extracted no text from {pdf_path.name}")
        except Exception as e:
            logger.warning(f"OCR extraction failed for {pdf_path.name}: {e}")
    elif not text.strip():
        logger.warning(f"All text extraction methods failed for {pdf_path.name}. OCR not available (requires pdf2image and pytesseract)")
    
    # Extract title from metadata or first line of text
    title = None
    if metadata:
        # Try different metadata key formats
        title = (metadata.get('/Title') or metadata.get('Title') or 
                metadata.get('title') or metadata.get('Subject') or 
                metadata.get('/Subject'))
        if title:
            title = str(title).strip()
            if not title or title == 'None':
                title = None
    
    if not title and text:
        # Try to extract title from first few lines
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines[:5]:  # Check first 5 non-empty lines
            if len(line) > 5 and len(line) < 200:
                # Check if it looks like a title (not too many words, not all caps)
                words = line.split()
                if 3 <= len(words) <= 20:
                    title = line
                    break
    
    # Log final result
    if text.strip():
        logger.info(f"PDF extraction complete for {pdf_path.name}: {len(text)} chars, method={extraction_method}, title={'found' if title else 'not found'}")
    else:
        logger.error(f"PDF extraction FAILED for {pdf_path.name}: No text extracted using any method")
    
    return PDFData(
        text=text,
        title=title,
        metadata=metadata
    )

