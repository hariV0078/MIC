"""PDF text extraction with multi-layer fallback: pdfplumber → PyPDF2 → EasyOCR."""
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# --- Dependency imports (all optional, graceful fallback) ---

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PyPDF2 = None
    PYPDF2_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False

try:
    from pdf2image import convert_from_path
    import shutil
    import numpy as np
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    convert_from_path = None
    PDF2IMAGE_AVAILABLE = False

from event_validator.types import PDFData


# ─────────────────────────────────────────────────────────────
# Layer 1: pdfplumber (handles tables + complex layouts)
# ─────────────────────────────────────────────────────────────
def _extract_with_pdfplumber(pdf_path: Path) -> tuple[str, dict]:
    """Layer 1: pdfplumber — better layout/table handling."""
    if not PDFPLUMBER_AVAILABLE:
        return "", {}
    try:
        parts = []
        metadata = {}
        with pdfplumber.open(pdf_path) as pdf:
            try:
                metadata = pdf.metadata or {}
            except Exception:
                pass
            for i, page in enumerate(pdf.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        parts.append(page_text.strip())
                        continue
                    # Fallback: try table extraction within page
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row in table:
                                if row:
                                    row_text = " ".join(str(c) for c in row if c)
                                    if row_text.strip():
                                        parts.append(row_text.strip())
                    # Try layout-preserved extraction
                    try:
                        layout_text = page.extract_text(layout=True)
                        if layout_text and layout_text.strip():
                            parts.append(layout_text.strip())
                    except Exception:
                        pass
                except Exception as e:
                    logger.debug(f"pdfplumber page {i} error: {e}")
                    continue
        return "\n".join(parts), metadata
    except Exception as e:
        logger.debug(f"pdfplumber failed for {pdf_path.name}: {e}")
        return "", {}


# ─────────────────────────────────────────────────────────────
# Layer 2: PyPDF2
# ─────────────────────────────────────────────────────────────
def _extract_with_pypdf2(pdf_path: Path) -> tuple[str, dict]:
    """Layer 2: PyPDF2 — standard text extraction."""
    if not PYPDF2_AVAILABLE:
        return "", {}
    try:
        parts = []
        metadata = {}
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            try:
                if reader.metadata:
                    metadata = {k: str(v) for k, v in reader.metadata.items() if k and v}
            except Exception:
                pass
            for i, page in enumerate(reader.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        parts.append(page_text.strip())
                except Exception as e:
                    logger.debug(f"PyPDF2 page {i} error: {e}")
                    continue
        return "\n".join(parts), metadata
    except Exception as e:
        logger.debug(f"PyPDF2 failed for {pdf_path.name}: {e}")
        return "", {}


# ─────────────────────────────────────────────────────────────
# Layer 3: EasyOCR on PDF pages (scanned / image-only PDFs)
# ─────────────────────────────────────────────────────────────
def _extract_with_easyocr(pdf_path: Path) -> str:
    """Layer 3: Convert PDF to image, then EasyOCR using hardcoded Poppler path."""
    
    # Try several common locations for Poppler binaries
    POPPLER_DIR = r"C:\tools\poppler\Library\bin"
    
    if not os.path.exists(POPPLER_DIR):
        POPPLER_DIR = r"C:\ProgramData\chocolatey\lib\poppler\tools\poppler-26.02.0\Library\bin"
    
    if not os.path.exists(POPPLER_DIR):
        POPPLER_DIR = r"C:\ProgramData\chocolatey\lib\poppler\tools\poppler-26.02.0\bin"

    if not os.path.exists(POPPLER_DIR):
        # Last resort: try checking if it's already in PATH via shutil.which
        import shutil
        found = shutil.which("pdftocairo")
        if found:
            POPPLER_DIR = os.path.dirname(found)

    print(f"\n🔄 Running OCR Fallback on {pdf_path.name}...")
    if os.path.exists(POPPLER_DIR):
        print(f"    [Poppler] Using binaries from: {POPPLER_DIR}")
    else:
        print(f"    [Poppler] WARNING: No Poppler path found. Falling back to system PATH.")
    
    try:
        if not PDF2IMAGE_AVAILABLE:
            print(f"❌ ERROR: pdf2image library not found. OCR cannot run.")
            return ""

        from event_validator.utils.ocr import get_reader
        reader = get_reader()
        if not reader: 
            return ""

        # Convert PDF to images using the explicit Poppler path
        # If POPPLER_DIR doesn't exist, convert_from_path will fall back to PATH
        print(f"    [OCR] Converting PDF to images (dpi=200)...")
        images = convert_from_path(
            str(pdf_path), 
            dpi=200, 
            poppler_path=POPPLER_DIR if os.path.exists(POPPLER_DIR) else None
        )
        
        if not images:
            print(f"    [OCR] WARNING: No images generated from PDF. Poppler might be failing.")
            return ""

        print(f"    [OCR] Generated {len(images)} images. Running OCR on each page...")
        parts = []
        for i, img in enumerate(images, 1):
            print(f"    [OCR] Processing page {i}/{len(images)}...")
            img_array = np.array(img)
            result = reader.readtext(img_array, detail=0)
            page_text = " ".join(result).strip()
            if page_text:
                parts.append(page_text)
                
        return "\n".join(parts)

    except Exception as e:
        print(f"\n🚨 OCR CRASHED ON {pdf_path.name}:\n{str(e)}\n")
        return ""


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
def _infer_title(metadata: dict, text: str) -> Optional[str]:
    """Try to infer a title from metadata or first lines of text."""
    title = (
        metadata.get('/Title') or metadata.get('Title') or
        metadata.get('title') or metadata.get('Subject') or
        metadata.get('/Subject')
    )
    if title:
        title = str(title).strip()
        if title and title.lower() != 'none':
            return title
    # Fallback: use first meaningful line
    if text:
        for line in text.split('\n')[:8]:
            line = line.strip()
            words = line.split()
            if 3 <= len(words) <= 20 and len(line) > 5:
                return line
    return None


def extract_pdf_text(pdf_path: Path) -> 'PDFData':
    """
    Extract text from a PDF using a 3-layer cascade:
      1. pdfplumber   — best for text + tables
      2. PyPDF2       — standard text layer extraction
      3. EasyOCR      — scanned/image-only PDFs (requires pdf2image + poppler)

    Always returns a PDFData object (never None).
    """
    if not isinstance(pdf_path, Path):
        pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        return PDFData(text="", metadata={})

    text = ""
    metadata = {}
    method = "none"

    # Layer 1: pdfplumber
    logger.debug(f"PDF Layer 1 (pdfplumber): {pdf_path.name}")
    text, metadata = _extract_with_pdfplumber(pdf_path)
    if text.strip():
        method = "pdfplumber"

    # Layer 2: PyPDF2
    if not text.strip():
        logger.debug(f"PDF Layer 2 (PyPDF2): {pdf_path.name}")
        text, meta2 = _extract_with_pypdf2(pdf_path)
        if text.strip():
            method = "PyPDF2"
        if not metadata and meta2:
            metadata = meta2

    # Layer 3: OCR Fallback (Slowest)
    if not text.strip():
        if os.environ.get("DISABLE_PDF_OCR") == "1":
            logger.info(f"Skipping OCR layer for {pdf_path.name} (DISABLE_PDF_OCR=1)")
        else:
            logger.info(f"Retrying with OCR Layer 3: {pdf_path.name}")
            method = "ocr"
            text = _extract_with_easyocr(pdf_path)
        if text.strip():
            method = "easyocr"

    title = _infer_title(metadata, text)

    if text.strip():
        logger.info(f"PDF extraction OK: {pdf_path.name} | method={method} | chars={len(text)}")
    else:
        logger.error(f"PDF extraction FAILED: {pdf_path.name} | All 3 layers returned empty text")

    return PDFData(
        text=text,
        title=title,
        metadata=metadata
    )
