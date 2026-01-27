"""
Smart rate limiter using token bucket algorithm for API rate limit management.
Tracks requests per minute and automatically adjusts delays to maximize throughput.
Includes jitter to prevent burst synchronization.
"""
import time
import threading
import random
from collections import deque
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter that tracks requests in a rolling window.
    Automatically calculates delay needed to stay under rate limit.
    
    For Gemini:
    - Free tier: ~15 RPM (requests per minute)
    - Paid tier: 1000+ RPM (varies by tier)
    """
    
    def __init__(
        self,
        requests_per_minute: int = 15,
        burst_size: Optional[int] = None,
        safety_factor: float = 0.9,  # Use 90% of limit to be safe
        jitter_enabled: bool = True,  # Enable jitter to prevent synchronization
        jitter_min: float = 0.9,  # Minimum spacing multiplier
        jitter_max: float = 1.6  # Maximum spacing multiplier
    ):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests allowed per minute
            burst_size: Maximum burst requests (defaults to requests_per_minute)
            safety_factor: Fraction of limit to use (0.9 = 90% of limit)
            jitter_enabled: Enable random jitter to prevent thread synchronization
            jitter_min: Minimum spacing multiplier (0.9 = 90% of calculated delay)
            jitter_max: Maximum spacing multiplier (1.6 = 160% of calculated delay)
        """
        # For high-throughput mode, use minimal safety factor (0.95 = 95%)
        # This allows maximum utilization while staying safe
        effective_safety = min(safety_factor, 0.95)  # Cap at 95% to prevent going over limit
        self.requests_per_minute = int(requests_per_minute * effective_safety)  # Apply safety factor
        self.burst_size = burst_size or self.requests_per_minute
        self.safety_factor = safety_factor
        self.jitter_enabled = jitter_enabled
        self.jitter_min = jitter_min
        self.jitter_max = jitter_max
        
        # Track request timestamps in a rolling window (last 60 seconds)
        self._request_times: deque = deque(maxlen=self.requests_per_minute * 2)
        self._lock = threading.Lock()
        
        # Track last request time for minimum spacing
        self._last_request_time: float = 0.0
        
        jitter_str = f"jitter: {jitter_min}-{jitter_max}x" if jitter_enabled else "no jitter"
        logger.info(
            f"Rate limiter initialized: {self.requests_per_minute} RPM "
            f"(safety: {safety_factor*100:.0f}%), burst: {self.burst_size}, {jitter_str}"
        )
    
    def estimate_tokens(self, prompt: str, has_image: bool = False) -> int:
        """
        Rough token estimation (1 token ≈ 4 characters for text, images count as ~1000 tokens).
        This is a simple heuristic - actual tokenization may vary.
        """
        text_tokens = len(prompt) // 4
        image_tokens = 1000 if has_image else 0
        return text_tokens + image_tokens
    
    def acquire(self, wait: bool = True, estimated_tokens: Optional[int] = None) -> float:
        """
        Acquire permission to make a request. Returns delay needed in seconds.
        
        Args:
            wait: If True, wait for the calculated delay. If False, return delay but don't wait.
            estimated_tokens: Optional token count for token-aware rate limiting.
                           If provided, larger requests get slightly longer delays.
        
        Returns:
            Delay that was applied (or would be applied) in seconds
        """
        with self._lock:
            now = time.time()
            
            # Remove requests older than 60 seconds
            cutoff_time = now - 60.0
            while self._request_times and self._request_times[0] < cutoff_time:
                self._request_times.popleft()
            
            # Calculate delay needed
            delay = 0.0
            
            # Token-aware adjustment: larger requests get slightly longer delays
            token_multiplier = 1.0
            if estimated_tokens:
                # For requests > 2000 tokens, add small delay multiplier
                if estimated_tokens > 2000:
                    token_multiplier = 1.2  # 20% longer delay for large requests
                elif estimated_tokens > 1000:
                    token_multiplier = 1.1  # 10% longer delay for medium requests
                # Small requests (< 1000 tokens) get no multiplier (token_multiplier = 1.0)
            
            # Check if we're at the limit
            if len(self._request_times) >= self.requests_per_minute:
                # Calculate how long to wait until oldest request expires
                oldest_request = self._request_times[0]
                time_until_oldest_expires = (oldest_request + 60.0) - now
                delay = max(0.0, time_until_oldest_expires + 0.1) * token_multiplier  # Apply token multiplier
                logger.debug(f"Rate limit reached ({len(self._request_times)}/{self.requests_per_minute}), waiting {delay:.2f}s (tokens: {estimated_tokens or 'unknown'})")
            else:
                # Not at limit, but ensure minimum spacing for burst protection
                # Calculate minimum time between requests
                min_interval = 60.0 / self.requests_per_minute
                time_since_last = now - self._last_request_time
                
                if time_since_last < min_interval:
                    delay = (min_interval - time_since_last) * token_multiplier
                    # REMOVED 1-second cap - we need full spacing for Gemini
                    # delay = min(delay, 1.0)  # REMOVED: This was preventing proper spacing
                else:
                    # No delay needed
                    delay = 0.0
            
            # Apply jitter to prevent thread synchronization
            if self.jitter_enabled and delay > 0:
                jitter_multiplier = random.uniform(self.jitter_min, self.jitter_max)
                delay = delay * jitter_multiplier
                logger.debug(f"Applied jitter: {jitter_multiplier:.2f}x → delay: {delay:.2f}s")
            
            # Wait if requested
            if wait and delay > 0:
                time.sleep(delay)
            
            # Record this request
            request_time = time.time()
            self._request_times.append(request_time)
            self._last_request_time = request_time
            
            return delay
    
    def get_current_rate(self) -> float:
        """Get current requests per minute based on recent requests."""
        with self._lock:
            now = time.time()
            cutoff_time = now - 60.0
            
            # Count requests in last 60 seconds
            recent_requests = sum(1 for t in self._request_times if t >= cutoff_time)
            return recent_requests
    
    def get_available_quota(self) -> int:
        """Get number of requests available in current window."""
        with self._lock:
            return max(0, self.requests_per_minute - len(self._request_times))
    
    def reset(self):
        """Reset the rate limiter (clear request history)."""
        with self._lock:
            self._request_times.clear()
            self._last_request_time = 0.0
            logger.info("Rate limiter reset")


# Global rate limiter instances
_global_rate_limiter: Optional[TokenBucketRateLimiter] = None
_global_groq_rate_limiter: Optional[TokenBucketRateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Get or create global Gemini rate limiter instance."""
    global _global_rate_limiter
    
    with _rate_limiter_lock:
        if _global_rate_limiter is None:
            import os
            # Default to 145 RPM (97% of Gemini's 150 RPM limit)
            # Gemini-2.5-pro limits: 150 RPM, 2M TPM, 10K RPD
            # Using 145 RPM for maximum throughput while staying safe
            requests_per_minute = int(os.getenv('GEMINI_RPM_LIMIT', '145'))
            safety_factor = float(os.getenv('RATE_LIMIT_SAFETY_FACTOR', '0.9'))
            jitter_enabled = os.getenv('GEMINI_JITTER_ENABLED', 'true').lower() == 'true'
            jitter_min = float(os.getenv('GEMINI_JITTER_MIN', '0.9'))
            jitter_max = float(os.getenv('GEMINI_JITTER_MAX', '1.6'))
            _global_rate_limiter = TokenBucketRateLimiter(
                requests_per_minute=requests_per_minute,
                safety_factor=safety_factor,
                jitter_enabled=jitter_enabled,
                jitter_min=jitter_min,
                jitter_max=jitter_max
            )
        
        return _global_rate_limiter


def get_groq_rate_limiter() -> TokenBucketRateLimiter:
    """Get or create global Groq rate limiter instance."""
    global _global_groq_rate_limiter
    
    with _rate_limiter_lock:
        if _global_groq_rate_limiter is None:
            import os
            # Default to 25 RPM for Groq free tier (very conservative to avoid hitting 30 RPM limit)
            # Groq free tier has 30 RPM limit, so we use 25 to leave buffer
            # Groq paid tiers can be higher (60+ RPM)
            # Allow override via GROQ_RPM_LIMIT environment variable
            requests_per_minute = int(os.getenv('GROQ_RPM_LIMIT', '25'))
            safety_factor = float(os.getenv('GROQ_RATE_LIMIT_SAFETY_FACTOR', '0.8'))  # Very conservative (80% of 25 = 20 RPM)
            jitter_enabled = os.getenv('GROQ_JITTER_ENABLED', 'true').lower() == 'true'
            jitter_min = float(os.getenv('GROQ_JITTER_MIN', '0.9'))
            jitter_max = float(os.getenv('GROQ_JITTER_MAX', '1.6'))
            _global_groq_rate_limiter = TokenBucketRateLimiter(
                requests_per_minute=requests_per_minute,
                safety_factor=safety_factor,
                jitter_enabled=jitter_enabled,
                jitter_min=jitter_min,
                jitter_max=jitter_max
            )
            logger.info(f"Groq rate limiter: {_global_groq_rate_limiter.requests_per_minute} RPM (effective: {int(requests_per_minute * safety_factor)} RPM)")
        
        return _global_groq_rate_limiter


def reset_rate_limiter():
    """Reset the global Gemini rate limiter."""
    global _global_rate_limiter
    with _rate_limiter_lock:
        if _global_rate_limiter:
            _global_rate_limiter.reset()


def reset_groq_rate_limiter():
    """Reset the global Groq rate limiter."""
    global _global_groq_rate_limiter
    with _rate_limiter_lock:
        if _global_groq_rate_limiter:
            _global_groq_rate_limiter.reset()
