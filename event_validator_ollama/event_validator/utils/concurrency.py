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

logger = logging.getLogger(__name__)

# Provider-specific concurrency limits
# Gemini-2.5-pro supports up to 10 concurrent calls (AFC max remote calls: 10)
# Using 6 concurrent calls for maximum throughput while staying safe
GEMINI_MAX_CONCURRENT = int(os.getenv('GEMINI_MAX_CONCURRENT', '6'))  # Increased from 4 to 6
GROQ_MAX_CONCURRENT = int(os.getenv('GROQ_MAX_CONCURRENT', '1'))

# Global semaphores (thread-safe)
_gemini_semaphore: Optional[threading.Semaphore] = None
_groq_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()


def _get_gemini_semaphore() -> threading.Semaphore:
    """Get or create Gemini semaphore."""
    global _gemini_semaphore
    with _semaphore_lock:
        if _gemini_semaphore is None:
            _gemini_semaphore = threading.Semaphore(GEMINI_MAX_CONCURRENT)
            logger.info(f"Gemini concurrency semaphore initialized: max {GEMINI_MAX_CONCURRENT} concurrent calls")
        return _gemini_semaphore


def _get_groq_semaphore() -> threading.Semaphore:
    """Get or create Groq semaphore."""
    global _groq_semaphore
    with _semaphore_lock:
        if _groq_semaphore is None:
            _groq_semaphore = threading.Semaphore(GROQ_MAX_CONCURRENT)
            logger.info(f"Groq concurrency semaphore initialized: max {GROQ_MAX_CONCURRENT} concurrent calls")
        return _groq_semaphore


@contextmanager
def gemini_concurrency_guard():
    """
    Context manager to limit concurrent Gemini API calls.
    
    Usage:
        with gemini_concurrency_guard():
            result = gemini_client.generate(...)
    
    This ensures at most GEMINI_MAX_CONCURRENT calls are in flight at once.
    """
    semaphore = _get_gemini_semaphore()
    acquired = False
    try:
        logger.debug("Acquiring Gemini concurrency semaphore...")
        semaphore.acquire()
        acquired = True
        logger.debug("Gemini concurrency semaphore acquired")
        yield
    finally:
        if acquired:
            semaphore.release()
            logger.debug("Gemini concurrency semaphore released")


@contextmanager
def groq_concurrency_guard():
    """
    Context manager to limit concurrent Groq API calls.
    
    Usage:
        with groq_concurrency_guard():
            result = groq_client.generate(...)
    
    This ensures at most GROQ_MAX_CONCURRENT calls are in flight at once.
    """
    semaphore = _get_groq_semaphore()
    acquired = False
    try:
        logger.debug("Acquiring Groq concurrency semaphore...")
        semaphore.acquire()
        acquired = True
        logger.debug("Groq concurrency semaphore acquired")
        yield
    finally:
        if acquired:
            semaphore.release()
            logger.debug("Groq concurrency semaphore released")


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
    gemini_sem = _get_gemini_semaphore()
    groq_sem = _get_groq_semaphore()
    
    # Note: _value is internal but useful for debugging
    # In production, track active calls separately
    return {
        "gemini_max_concurrent": GEMINI_MAX_CONCURRENT,
        "groq_max_concurrent": GROQ_MAX_CONCURRENT,
        "gemini_semaphore_initialized": _gemini_semaphore is not None,
        "groq_semaphore_initialized": _groq_semaphore is not None
    }


def reset_semaphores():
    """Reset semaphores (for testing)."""
    global _gemini_semaphore, _groq_semaphore
    with _semaphore_lock:
        _gemini_semaphore = None
        _groq_semaphore = None
        logger.info("Concurrency semaphores reset")
