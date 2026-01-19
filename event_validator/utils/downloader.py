"""Utilities for downloading files from URLs (Azure Blob Storage, etc.)."""
import logging
import os
from pathlib import Path
from typing import Optional
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Directory to save downloaded files (current working directory)
DOWNLOAD_DIR = Path.cwd() / "downloaded_files"
DOWNLOAD_DIR.mkdir(exist_ok=True)


def download_file(
    url: str,
    timeout: int = 30,
    try_alternatives: bool = False,  # Disabled - no fallbacks
    event_driven: Optional[int] = None,
    academic_year: Optional[str] = None
) -> Optional[Path]:
    """
    Download a file from a URL to a temporary file - NO fallbacks, NO retries.
    
    If the URL fails, returns None and continues validation.
    
    Args:
        url: URL to download
        timeout: Request timeout
        try_alternatives: IGNORED - kept for compatibility but always False
        event_driven: IGNORED - kept for compatibility
        academic_year: IGNORED - kept for compatibility
    
    Returns Path to temporary file, or None if download failed.
    """
    logger.info(f"Downloading file from URL: {url}")
    
    result = _download_file_single(url, timeout)
    if result:
        logger.info(f"Download succeeded: {url}")
        return result
    else:
        logger.warning(f"Download failed (404 or error): {url} - marking file as missing")
        return None


def _download_file_single(url: str, timeout: int = 30) -> Optional[Path]:
    """
    Single attempt to download a file from URL.
    
    Saves file to current directory (downloaded_files/) instead of temp directory.
    Files are kept until manually cleaned up.
    
    Returns Path to downloaded file, or None if download failed.
    """
    try:
        logger.debug(f"Attempting download from URL: {url}")
        
        # Download file
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        
        # Create filename from URL
        parsed_url = urlparse(url)
        url_path = Path(parsed_url.path)
        filename = url_path.name or "downloaded_file"
        
        # If filename is empty or generic, use hash of URL
        if not filename or filename == "downloaded_file":
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            file_extension = url_path.suffix or '.tmp'
            filename = f"event_validator_{url_hash}{file_extension}"
        
        # Ensure unique filename in download directory
        download_path = DOWNLOAD_DIR / filename
        counter = 1
        while download_path.exists():
            stem = download_path.stem
            suffix = download_path.suffix
            download_path = DOWNLOAD_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
        
        # Download and save file
        with open(download_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        logger.debug(f"Successfully downloaded file to: {download_path}")
        return download_path
        
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            logger.debug(f"404 Not Found: {url}")
        else:
            logger.debug(f"HTTP error downloading {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.debug(f"Request error downloading {url}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected error downloading {url}: {e}")
        return None


def download_pdf(
    url: str,
    event_driven: Optional[int] = None,
    academic_year: Optional[str] = None
) -> Optional[Path]:
    """Download a PDF file from URL - NO fallbacks."""
    return download_file(url, event_driven=event_driven, academic_year=academic_year)


def download_image(
    url: str,
    event_driven: Optional[int] = None,
    academic_year: Optional[str] = None
) -> Optional[Path]:
    """Download an image file from URL - NO fallbacks."""
    return download_file(url, event_driven=event_driven, academic_year=academic_year)
