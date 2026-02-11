"""PDF text extraction functionality."""
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass

try:
    import pypdf
    PDF_AVAILABLE = True
except ImportError:
    pypdf = None
    PDF_AVAILABLE = False

logger = logging.getLogger(__name__)

@dataclass
class PDFData:
    text: str
    num_pages: int
    metadata: Dict[str, Any]
    title: Optional[str] = None
    author: Optional[str] = None

def extract_pdf_data_from_bytes(pdf_bytes: bytes) -> Optional[PDFData]:
    """
    Extract text and metadata from PDF bytes.
    """
    if not PDF_AVAILABLE:
        logger.error("pypdf not installed. Cannot extract PDF data.")
        return None
        
    try:
        # Create a BytesIO object
        from io import BytesIO
        pdf_file = BytesIO(pdf_bytes)
        
        reader = pypdf.PdfReader(pdf_file)
        num_pages = len(reader.pages)
        
        # Extract metadata
        metadata = {}
        if reader.metadata:
            metadata = {k: str(v) for k, v in reader.metadata.items()}
            
        title = metadata.get('/Title')
        author = metadata.get('/Author')
        
        # Extract text from all pages
        text = ""
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
                
        return PDFData(
            text=text,
            num_pages=num_pages,
            metadata=metadata,
            title=title,
            author=author
        )
        
    except Exception as e:
        logger.error(f"Error extracting PDF data from bytes: {e}")
        return None

def extract_pdf_text(file_path: Path) -> Optional[PDFData]:
    """
    Extract text from a PDF file.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        PDFData object or None if extraction fails
    """
    if not PDF_AVAILABLE:
        logger.warning("pypdf library not available. Install it with: pip install pypdf")
        return None
        
    try:
        reader = pypdf.PdfReader(str(file_path))
        text = ""
        
        # Extract text from all pages
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            except Exception as e:
                logger.warning(f"Failed to extract text from page in {file_path}: {e}")
                continue
                
        # Extract metadata
        metadata = {}
        try:
            if reader.metadata:
                # Convert metadata to dict
                for key, value in reader.metadata.items():
                    if key and value:
                        metadata[str(key)] = str(value)
        except Exception:
            pass
            
        return PDFData(
            text=text,
            num_pages=len(reader.pages),
            metadata=metadata,
            title=metadata.get('/Title'),
            author=metadata.get('/Author')
        )
        
    except Exception as e:
        logger.error(f"Error extracting PDF {file_path}: {e}")
        return None
