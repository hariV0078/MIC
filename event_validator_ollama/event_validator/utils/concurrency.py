"""
Provider-level concurrency control using semaphores.
Prevents burst 429 errors by limiting concurrent API calls per provider.

This is CRITICAL for Gemini which has very low tolerance for concurrent requests.
"""
import threading
import logging
import os
import random
import time
from typing import Optional
from contextlib import contextmanager
from dotenv import load_dotenv

# Load environment variables early for semaphore initialization
load_dotenv()

logger = logging.getLogger(__name__)

# Concurrency limits
OLLAMA_MAX_CONCURRENT = int(os.getenv('OLLAMA_MAX_CONCURRENT', '2'))

# Global semaphores (thread-safe)
_ollama_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()


def _get_ollama_semaphore() -> threading.Semaphore:
    """Get or create Ollama semaphore."""
    global _ollama_semaphore
    with _semaphore_lock:
        if _ollama_semaphore is None:
            _ollama_semaphore = threading.Semaphore(OLLAMA_MAX_CONCURRENT)
            logger.info(f"Ollama concurrency semaphore initialized: max {OLLAMA_MAX_CONCURRENT} concurrent calls")
        return _ollama_semaphore


@contextmanager
def ollama_concurrency_guard():
    """
    Context manager to limit concurrent Ollama API calls.
    
    Usage:
        with ollama_concurrency_guard():
            result = ollama_client.generate(...)
    
    This ensures at most OLLAMA_MAX_CONCURRENT calls are in flight at once.
    """
    semaphore = _get_ollama_semaphore()
    acquired = False
    try:
        logger.debug("Acquiring Ollama concurrency semaphore...")
        semaphore.acquire()
        acquired = True
        logger.debug("Ollama concurrency semaphore acquired")
        yield
    finally:
        if acquired:
            semaphore.release()
            logger.debug("Ollama concurrency semaphore released")


def stagger_request(min_delay: float = 0.1, max_delay: float = 0.4):
    """
    Add random stagger delay to prevent thundering herd.
    
    Call this BEFORE making the first LLM call in a submission.
    This dramatically reduces burst pressure on both Gemini and Groq.
    
    Args:
        min_delay: Minimum delay in seconds (default 0.1)
        max_delay: Maximum delay in seconds (default 0.4)
    """
    delay = random.uniform(min_delay, max_delay)
    logger.debug(f"Staggering request by {delay:.3f}s to prevent thundering herd")
    time.sleep(delay)


def get_concurrency_stats() -> dict:
    """Get current concurrency stats for monitoring."""
    return {
        "ollama_max_concurrent": OLLAMA_MAX_CONCURRENT,
        "ollama_semaphore_initialized": _ollama_semaphore is not None
    }


def reset_semaphores():
    """Reset semaphores (for testing)."""
    global _ollama_semaphore
    with _semaphore_lock:
        _ollama_semaphore = None
        logger.info("Concurrency semaphores reset")


# Alias for backward compatibility with Gemini-based code
gemini_concurrency_guard = ollama_concurrency_guard
