"""
Request budget tracker to limit API calls per submission.
Prevents regression to excessive API usage.
"""
import logging
import threading
from typing import Optional, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RequestBudget:
    """
    Tracks API calls made for a single submission.
    Enforces maximum calls per submission to prevent regression.
    """
    submission_id: str
    max_calls: int = 5  # Default: 5 calls per submission
    calls_used: int = 0
    call_history: list = field(default_factory=list)
    
    def can_make_call(self, call_type: str = "unknown") -> bool:
        """
        Check if another API call can be made.
        
        Args:
            call_type: Type of call (for logging)
        
        Returns:
            True if call can be made, False if budget exhausted
        """
        if self.calls_used >= self.max_calls:
            logger.warning(
                f"Request budget exhausted for submission {self.submission_id}: "
                f"{self.calls_used}/{self.max_calls} calls used. "
                f"Call type: {call_type}"
            )
            return False
        return True
    
    def record_call(self, call_type: str = "unknown", success: bool = True):
        """
        Record an API call.
        
        Args:
            call_type: Type of call (e.g., "theme", "pdf", "image")
            success: Whether the call was successful
        """
        self.calls_used += 1
        self.call_history.append({
            "type": call_type,
            "success": success,
            "call_number": self.calls_used
        })
        
        if self.calls_used >= self.max_calls:
            logger.warning(
                f"Request budget limit reached for submission {self.submission_id}: "
                f"{self.calls_used}/{self.max_calls} calls"
            )
    
    def get_remaining_calls(self) -> int:
        """Get number of remaining API calls."""
        return max(0, self.max_calls - self.calls_used)
    
    def get_summary(self) -> dict:
        """Get budget summary."""
        return {
            "submission_id": self.submission_id,
            "calls_used": self.calls_used,
            "max_calls": self.max_calls,
            "remaining": self.get_remaining_calls(),
            "call_history": self.call_history
        }


# Global budget tracker (thread-safe)
_budget_tracker: Dict[str, RequestBudget] = {}
_budget_lock = threading.Lock()


def get_budget(submission_id: str, max_calls: Optional[int] = None) -> RequestBudget:
    """
    Get or create budget for a submission.
    
    Args:
        submission_id: Unique submission identifier
        max_calls: Maximum calls allowed (defaults to env var or 5)
    
    Returns:
        RequestBudget instance
    """
    import os
    
    if max_calls is None:
        max_calls = int(os.getenv('MAX_API_CALLS_PER_SUBMISSION', '5'))
    
    with _budget_lock:
        if submission_id not in _budget_tracker:
            _budget_tracker[submission_id] = RequestBudget(
                submission_id=submission_id,
                max_calls=max_calls
            )
        
        return _budget_tracker[submission_id]


def reset_budget(submission_id: Optional[str] = None):
    """
    Reset budget for a submission or all submissions.
    
    Args:
        submission_id: If provided, reset only this submission. Otherwise reset all.
    """
    with _budget_lock:
        if submission_id:
            if submission_id in _budget_tracker:
                del _budget_tracker[submission_id]
                logger.debug(f"Reset budget for submission {submission_id}")
        else:
            _budget_tracker.clear()
            logger.debug("Reset all budgets")


def get_all_budgets() -> Dict[str, RequestBudget]:
    """Get all active budgets (for monitoring)."""
    with _budget_lock:
        return _budget_tracker.copy()
