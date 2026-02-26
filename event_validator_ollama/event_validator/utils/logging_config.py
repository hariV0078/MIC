"""Logging configuration for the event validation system."""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(log_level: str = "INFO", log_file: Optional[Path] = None):
    """Configure logging for the application."""
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))
    class SafeStreamHandler(logging.StreamHandler):
        """A StreamHandler that gracefully ignores [Errno 5] Input/output error on Ubuntu/Linux."""
        def emit(self, record):
            try:
                super().emit(record)
            except OSError as e:
                # 5 is EIO (Input/output error)
                if e.errno == 5:
                    pass
                else:
                    raise
            except Exception:
                self.handleError(record)

    # Console handler using safe EIO stream
    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

