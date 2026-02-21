"""PDF text extraction with multi-layer fallback: pypdf → pdfplumber → EasyOCR."""
import logging
import os
from typing import Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# --- Dependency imports (all optional, graceful fallback) ---

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    pypdf = None
    PYPDF_AVAILABLE = False

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


@dataclass
class PDFData:
    text: str
    num_pages: int
    metadata: Dict[str, Any]
    title: Optional[str] = None
    author: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Layer 1: pypdf
# ─────────────────────────────────────────────────────────────
def _extract_with_pypdf(pdf_path: Path) -> tuple[str, dict]:
    """Layer 1: Extract text using pypdf (fast, text-based PDFs only)."""
    if not PYPDF_AVAILABLE:
        return "", {}
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        parts = []
        for page in reader.pages:
            try:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    parts.append(page_text.strip())
            except Exception:
                continue
        metadata = {}
        try:
            if reader.metadata:
                metadata = {k: str(v) for k, v in reader.metadata.items() if k and v}
        except Exception:
            pass
        return "\n".join(parts), metadata
    except Exception as e:
        logger.debug(f"pypdf failed for {pdf_path.name}: {e}")
        return "", {}


# ─────────────────────────────────────────────────────────────
# Layer 2: pdfplumber (handles tables, complex layouts)
# ─────────────────────────────────────────────────────────────
def _extract_with_pdfplumber(pdf_path: Path) -> tuple[str, dict]:
    """Layer 2: Extract text using pdfplumber (better layout handling)."""
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
                    # Try table extraction as fallback within page
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row in table:
                                if row:
                                    row_text = " ".join(str(c) for c in row if c)
                                    if row_text.strip():
                                        parts.append(row_text.strip())
                except Exception as e:
                    logger.debug(f"pdfplumber page {i} failed: {e}")
                    continue
        return "\n".join(parts), metadata
    except Exception as e:
        logger.debug(f"pdfplumber failed for {pdf_path.name}: {e}")
        return "", {}


# ─────────────────────────────────────────────────────────────
# Layer 3: EasyOCR on PDF pages (scanned / image-based PDFs)
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
        # OPTIMIZED: 150 DPI and limit to first 5 pages for speed
        print(f"    [OCR] Converting PDF to images (dpi=150, limit=5 pages)...")
        images = convert_from_path(
            str(pdf_path), 
            dpi=150, 
            last_page=5,
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

    # Fallback: use first meaningful line of extracted text
    if text:
        for line in text.split('\n')[:8]:
            line = line.strip()
            words = line.split()
            if 3 <= len(words) <= 20 and len(line) > 5:
                return line
    return None


def extract_pdf_text(file_path: Path) -> Optional[PDFData]:
    """
    Extract text from a PDF using a 3-layer cascade:
      1. pypdf        — fast, works for text-layer PDFs
      2. pdfplumber   — better layout / table handling
      3. EasyOCR      — image-based / scanned PDFs (requires pdf2image + poppler)

    Returns PDFData even if all layers fail (with empty text).
    Never returns None so the caller can safely check pdf_data.text.
    """
    if not isinstance(file_path, Path):
        file_path = Path(file_path)

    if not file_path.exists():
        logger.error(f"PDF file not found: {file_path}")
        return PDFData(text="", num_pages=0, metadata={})

    text = ""
    metadata = {}
    method = "none"

    # --- Layer 1: pypdf ---
    print(f"🔎 [DEBUG] Layer 1 (pypdf) starting for: {file_path.name}")
    text, metadata = _extract_with_pypdf(file_path)
    if text.strip():
        print(f"✅ [DEBUG] Layer 1 (pypdf) SUCCESS: Extracted {len(text)} chars")
        method = "pypdf"

    # --- Layer 2: pdfplumber ---
    if not text.strip():
        print(f"🔎 [DEBUG] Layer 2 (pdfplumber) starting for: {file_path.name}")
        text, meta2 = _extract_with_pdfplumber(file_path)
        if text.strip():
            print(f"✅ [DEBUG] Layer 2 (pdfplumber) SUCCESS: Extracted {len(text)} chars")
            method = "pdfplumber"
        if not metadata and meta2:
            metadata = meta2

    # --- Layer 3: EasyOCR ---
    if not text.strip():
        print(f"🔎 [DEBUG] Layer 3 (EasyOCR) target check: DISABLE_PDF_OCR={os.environ.get('DISABLE_PDF_OCR')}")
        if os.environ.get("DISABLE_PDF_OCR") == "1":
            logger.info(f"Skipping OCR layer for {file_path.name} (DISABLE_PDF_OCR=1)")
        else:
            logger.info(f"PDF Layer 3 (EasyOCR): {file_path.name} — text PDFs failed, trying OCR")
            text = _extract_with_easyocr(file_path)
            if text.strip():
                print(f"✅ [DEBUG] Layer 3 (EasyOCR) SUCCESS: Extracted {len(text)} chars")
        if text.strip():
            method = "easyocr"
    else:
        print(f"⏭️ [DEBUG] Skipping Layer 3 (OCR) because text is already present.")

    if not text.strip():
        print(f"❌ [DEBUG] ALL PDF EXTRACTION LAYERS FAILED for: {file_path.name}")

    # Get page count (best-effort)
    num_pages = 0
    try:
        if PYPDF_AVAILABLE:
            reader = pypdf.PdfReader(str(file_path))
            num_pages = len(reader.pages)
    except Exception:
        pass

    title = _infer_title(metadata, text)

    if text.strip():
        logger.info(f"PDF extraction OK: {file_path.name} | method={method} | chars={len(text)} | pages={num_pages}")
    else:
        logger.error(f"PDF extraction FAILED: {file_path.name} | All 3 layers returned empty text")

    return PDFData(
        text=text,
        num_pages=num_pages,
        metadata=metadata,
        title=title,
        author=metadata.get('/Author') or metadata.get('Author'),
    )


def extract_pdf_data_from_bytes(pdf_bytes: bytes) -> Optional[PDFData]:
    """
    Extract text from raw PDF bytes (used when PDF is already in memory).
    Writes to a temp file and delegates to extract_pdf_text.
    """
    import tempfile
    import os
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = Path(tmp.name)
        result = extract_pdf_text(tmp_path)
        return result
    except Exception as e:
        logger.error(f"extract_pdf_data_from_bytes failed: {e}")
        return PDFData(text="", num_pages=0, metadata={})
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
