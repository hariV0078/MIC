"""
Circuit breaker for API rate limit protection.
Prevents hammering APIs during sustained throttling periods.
"""
import time
import threading
import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker that opens when error rate exceeds threshold.
    
    Prevents cascading failures by blocking requests when API is consistently
    returning rate limit errors (429).
    """
    
    def __init__(
        self,
        error_threshold: float = 0.70,  # 70% error rate (very lenient - was 50%)
        window_duration: float = 30.0,  # 30 seconds (was 60 - shorter window)
        cooldown_duration: float = 10.0,  # 10 seconds (was 15 - faster recovery)
        half_open_max_attempts: int = 1,  # 1 attempt to recover (was 3)
        min_errors_to_open: int = 20,  # Minimum errors before opening (was 10 - need more!)
        name: str = "default"
    ):
        """
        Initialize circuit breaker.
        
        Args:
            error_threshold: Error rate threshold (0.50 = 50%)
            window_duration: Time window in seconds for error rate calculation
            cooldown_duration: How long to stay open before trying half-open
            half_open_max_attempts: Max attempts allowed in half-open state
            min_errors_to_open: Minimum absolute errors required before opening
            name: Name for logging
        """
        self.error_threshold = error_threshold
        self.window_duration = window_duration
        self.cooldown_duration = cooldown_duration
        self.half_open_max_attempts = half_open_max_attempts
        self.min_errors_to_open = min_errors_to_open
        self.name = name
        
        # State tracking
        self.state = CircuitState.CLOSED
        self.error_count = 0
        self.success_count = 0
        self.total_requests = 0
        self.window_start = time.time()
        self.open_until: Optional[float] = None
        self.half_open_attempts = 0
        
        # Thread safety
        self._lock = threading.Lock()
        
        logger.info(
            f"Circuit breaker '{name}' initialized: "
            f"threshold={error_threshold*100:.1f}%, "
            f"min_errors={min_errors_to_open}, "
            f"window={window_duration}s, "
            f"cooldown={cooldown_duration}s"
        )
    
    def record_success(self):
        """Record a successful API call."""
        with self._lock:
            self.total_requests += 1
            self.success_count += 1
            
            if self.state == CircuitState.HALF_OPEN:
                # If we get successes in half-open, close the circuit
                if self.half_open_attempts >= self.half_open_max_attempts:
                    self.state = CircuitState.CLOSED
                    self.half_open_attempts = 0
                    logger.info(f"Circuit breaker '{self.name}' CLOSED: Service recovered")
                else:
                    self.half_open_attempts += 1
            elif self.state == CircuitState.OPEN:
                # Reset error count on success (helps recovery)
                self.error_count = max(0, self.error_count - 1)
            
            self._check_window_reset()
    
    def record_error(self, is_rate_limit: bool = True):
        """
        Record an API error.
        
        Args:
            is_rate_limit: Whether this is a rate limit error (429)
        """
        with self._lock:
            self.total_requests += 1
            
            if is_rate_limit:
                self.error_count += 1
            
            if self.state == CircuitState.HALF_OPEN:
                # If we get errors in half-open, open the circuit again
                self.state = CircuitState.OPEN
                self.open_until = time.time() + self.cooldown_duration
                self.half_open_attempts = 0
                logger.warning(
                    f"Circuit breaker '{self.name}' OPEN: "
                    f"Errors detected in half-open state"
                )
            
            self._check_threshold()
            self._check_window_reset()
    
    def can_proceed(self) -> bool:
        """
        Check if request can proceed.
        
        Returns:
            True if request can proceed, False if circuit is open
        """
        with self._lock:
            now = time.time()
            
            # Check if we should transition from OPEN to HALF_OPEN
            if self.state == CircuitState.OPEN:
                if self.open_until and now >= self.open_until:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_attempts = 0
                    logger.info(
                        f"Circuit breaker '{self.name}' HALF_OPEN: "
                        f"Testing if service recovered"
                    )
                    return True
                else:
                    return False
            
            # HALF_OPEN and CLOSED states allow requests
            return True
    
    def _check_threshold(self):
        """Check if error rate exceeds threshold."""
        if self.state == CircuitState.OPEN:
            return  # Already open
        
        if self.total_requests == 0:
            return  # No requests yet
        
        # Calculate error rate
        elapsed = time.time() - self.window_start
        if elapsed > 0:
            error_rate = self.error_count / max(1, self.total_requests)
            
            # Check if we should open the circuit
            # MUST have BOTH: minimum absolute errors AND error rate exceeded
            if (error_rate >= self.error_threshold and 
                self.error_count >= self.min_errors_to_open and 
                self.total_requests >= 10):
                # Only open if we have enough data (at least 10 requests)
                self.state = CircuitState.OPEN
                self.open_until = time.time() + self.cooldown_duration
                logger.warning(
                    f"Circuit breaker '{self.name}' OPEN: "
                    f"Error rate {error_rate*100:.1f}% >= threshold {self.error_threshold*100:.1f}% "
                    f"({self.error_count}/{self.total_requests} errors in {elapsed:.1f}s)"
                )
    
    def _check_window_reset(self):
        """Reset window if it has expired."""
        elapsed = time.time() - self.window_start
        if elapsed > self.window_duration:
            # Reset window
            logger.debug(
                f"Circuit breaker '{self.name}': Resetting window "
                f"(errors: {self.error_count}/{self.total_requests})"
            )
            self.error_count = 0
            self.success_count = 0
            self.total_requests = 0
            self.window_start = time.time()
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self.state
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        with self._lock:
            elapsed = time.time() - self.window_start
            if self.total_requests > 0:
                error_rate = self.error_count / self.total_requests
            else:
                error_rate = 0.0
            
            return {
                "state": self.state.value,
                "error_count": self.error_count,
                "success_count": self.success_count,
                "total_requests": self.total_requests,
                "error_rate": error_rate,
                "window_elapsed": elapsed,
                "open_until": self.open_until,
                "half_open_attempts": self.half_open_attempts
            }
    
    def reset(self):
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.error_count = 0
            self.success_count = 0
            self.total_requests = 0
            self.window_start = time.time()
            self.open_until = None
            self.half_open_attempts = 0
            logger.info(f"Circuit breaker '{self.name}' manually reset")


# Global circuit breaker instances
_gemini_circuit_breaker: Optional[CircuitBreaker] = None
_groq_circuit_breaker: Optional[CircuitBreaker] = None
_circuit_breaker_lock = threading.Lock()


def get_gemini_circuit_breaker() -> CircuitBreaker:
    """Get or create global Gemini circuit breaker."""
    global _gemini_circuit_breaker
    
    with _circuit_breaker_lock:
        if _gemini_circuit_breaker is None:
            import os
            # VERY LENIENT defaults: 70% error rate, 10s cooldown, min 20 errors
            error_threshold = float(os.getenv('GEMINI_CIRCUIT_BREAKER_THRESHOLD', '0.70'))
            window_duration = float(os.getenv('GEMINI_CIRCUIT_BREAKER_WINDOW', '30'))
            cooldown_duration = float(os.getenv('GEMINI_CIRCUIT_BREAKER_COOLDOWN', '10'))
            min_errors = int(os.getenv('GEMINI_CIRCUIT_BREAKER_MIN_ERRORS', '20'))
            
            _gemini_circuit_breaker = CircuitBreaker(
                error_threshold=error_threshold,
                window_duration=window_duration,
                cooldown_duration=cooldown_duration,
                min_errors_to_open=min_errors,
                name="gemini"
            )
        
        return _gemini_circuit_breaker


def get_groq_circuit_breaker() -> CircuitBreaker:
    """Get or create global Groq circuit breaker."""
    global _groq_circuit_breaker
    
    with _circuit_breaker_lock:
        if _groq_circuit_breaker is None:
            import os
            # VERY LENIENT defaults: 70% error rate, 10s cooldown, min 20 errors
            error_threshold = float(os.getenv('GROQ_CIRCUIT_BREAKER_THRESHOLD', '0.70'))
            window_duration = float(os.getenv('GROQ_CIRCUIT_BREAKER_WINDOW', '30'))
            cooldown_duration = float(os.getenv('GROQ_CIRCUIT_BREAKER_COOLDOWN', '10'))
            min_errors = int(os.getenv('GROQ_CIRCUIT_BREAKER_MIN_ERRORS', '20'))
            
            _groq_circuit_breaker = CircuitBreaker(
                error_threshold=error_threshold,
                window_duration=window_duration,
                cooldown_duration=cooldown_duration,
                min_errors_to_open=min_errors,
                name="groq"
            )
        
        return _groq_circuit_breaker


def reset_gemini_circuit_breaker():
    """Reset Gemini circuit breaker."""
    with _circuit_breaker_lock:
        if _gemini_circuit_breaker:
            _gemini_circuit_breaker.reset()


def reset_groq_circuit_breaker():
    """Reset Groq circuit breaker."""
    with _circuit_breaker_lock:
        if _groq_circuit_breaker:
            _groq_circuit_breaker.reset()
