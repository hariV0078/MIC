"""Utilities for downloading files from URLs (Azure Blob Storage, etc.)."""
import logging
import os
import time
import threading
from pathlib import Path
from typing import Optional
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Directory to save downloaded files (current working directory)
DOWNLOAD_DIR = Path.cwd() / "downloaded_files"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Cleanup configuration (in seconds)
CLEANUP_INTERVAL = int(os.getenv("CLEANUP_INTERVAL", "3600"))  # Default: 1 hour
FILE_MAX_AGE = int(os.getenv("FILE_MAX_AGE", "86400"))  # Default: 24 hours (1 day)

# Global cleanup thread
_cleanup_thread: Optional[threading.Thread] = None
_cleanup_running = False


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


def cleanup_old_files(max_age_seconds: Optional[int] = None) -> int:
    """
    Delete files in DOWNLOAD_DIR that are older than max_age_seconds.
    
    Args:
        max_age_seconds: Maximum age of files in seconds. Defaults to FILE_MAX_AGE.
    
    Returns:
        Number of files deleted.
    """
    if max_age_seconds is None:
        max_age_seconds = FILE_MAX_AGE
    
    if not DOWNLOAD_DIR.exists():
        return 0
    
    current_time = time.time()
    deleted_count = 0
    total_size_freed = 0
    
    try:
        for file_path in DOWNLOAD_DIR.iterdir():
            if file_path.is_file():
                try:
                    # Get file modification time
                    file_age = current_time - file_path.stat().st_mtime
                    
                    if file_age > max_age_seconds:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        deleted_count += 1
                        total_size_freed += file_size
                        logger.debug(f"Deleted old file: {file_path.name} (age: {file_age/3600:.2f} hours)")
                except OSError as e:
                    logger.warning(f"Failed to delete file {file_path}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"Cleanup completed: Deleted {deleted_count} file(s), "
                f"freed {total_size_freed / (1024*1024):.2f} MB"
            )
        else:
            logger.debug("Cleanup completed: No old files to delete")
            
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
    
    return deleted_count


def cleanup_all_files() -> int:
    """
    Delete all files in DOWNLOAD_DIR regardless of age.
    
    Returns:
        Number of files deleted.
    """
    if not DOWNLOAD_DIR.exists():
        return 0
    
    deleted_count = 0
    total_size_freed = 0
    
    try:
        for file_path in DOWNLOAD_DIR.iterdir():
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    total_size_freed += file_size
                except OSError as e:
                    logger.warning(f"Failed to delete file {file_path}: {e}")
        
        if deleted_count > 0:
            logger.info(
                f"Cleanup completed: Deleted {deleted_count} file(s), "
                f"freed {total_size_freed / (1024*1024):.2f} MB"
            )
            
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
    
    return deleted_count


def _periodic_cleanup_worker():
    """Background worker thread for periodic cleanup."""
    global _cleanup_running
    _cleanup_running = True
    
    logger.info(f"Starting periodic cleanup worker (interval: {CLEANUP_INTERVAL}s, max age: {FILE_MAX_AGE}s)")
    
    while _cleanup_running:
        try:
            cleanup_old_files()
        except Exception as e:
            logger.error(f"Error in periodic cleanup worker: {e}")
        
        # Sleep in small intervals to allow for quick shutdown
        for _ in range(CLEANUP_INTERVAL):
            if not _cleanup_running:
                break
            time.sleep(1)
    
    logger.info("Periodic cleanup worker stopped")


def start_periodic_cleanup():
    """Start the periodic cleanup background thread."""
    global _cleanup_thread, _cleanup_running
    
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        logger.warning("Periodic cleanup thread is already running")
        return
    
    _cleanup_running = True
    _cleanup_thread = threading.Thread(target=_periodic_cleanup_worker, daemon=True)
    _cleanup_thread.start()
    logger.info("Periodic cleanup started")


def stop_periodic_cleanup():
    """Stop the periodic cleanup background thread."""
    global _cleanup_thread, _cleanup_running
    
    if _cleanup_thread is None:
        return
    
    _cleanup_running = False
    if _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=5)
        logger.info("Periodic cleanup stopped")
