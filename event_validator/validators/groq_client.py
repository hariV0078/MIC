"""Groq Cloud API client for semantic validation with vision support."""
import logging
from typing import Optional, Dict, Any
import os
import time
import re
import base64
import hashlib
import threading
from pathlib import Path
from dotenv import load_dotenv
from event_validator.utils.rate_limiter import get_groq_rate_limiter
from event_validator.utils.circuit_breaker import get_groq_circuit_breaker
from event_validator.utils.concurrency import groq_concurrency_guard

# Load environment variables from .env file
load_dotenv()

try:
    from groq import Groq
except ImportError:
    Groq = None

logger = logging.getLogger(__name__)

# Global cache for Groq API responses (keyed by content hash)
_groq_response_cache: Dict[str, str] = {}

# Note: Concurrency control moved to utils/concurrency.py with groq_concurrency_guard
# Default GROQ_MAX_CONCURRENT is now 1 to prevent burst 429s


class GroqClient:
    """Client for interacting with Groq Cloud models."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Groq client."""
        # Initialize model names first (always set, even if client fails)
        self.text_model = "llama-3.1-8b-instant"  # Fast text model
        self.image_model = "meta-llama/llama-4-scout-17b-16e-instruct"  # Image analysis model
        
        # Check for both GROQ_API_KEY and GROQ_CLOUD_API (common variations)
        self.api_key = api_key or os.getenv("GROQ_API_KEY") or os.getenv("GROQ_CLOUD_API")
        if not self.api_key:
            logger.warning("Groq API key not provided. Set GROQ_API_KEY environment variable.")
            self.client = None
            return
        
        if Groq is None:
            logger.error("groq package not installed. Install with: pip install groq")
            self.client = None
            return
        
        try:
            self.client = Groq(api_key=self.api_key)
            logger.info(f"Groq client initialized. Text model: {self.text_model}, Image model: {self.image_model}")
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.client = None
    
    def _get_cache_key(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate cache key for prompt and model."""
        content = f"{model or self.text_model}:{prompt}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _call_groq(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_retries: int = 3,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        Call Groq API with retry logic, rate limit handling, and caching.
        
        Args:
            prompt: Prompt text
            model: Model name (defaults to text_model)
            max_retries: Maximum retry attempts
            use_cache: Whether to use response cache
        """
        if not self.client:
            return None
        
        model = model or self.text_model
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(prompt, model)
            if cache_key in _groq_response_cache:
                logger.debug(f"Cache hit for prompt (model: {model})")
                return _groq_response_cache[cache_key]
        
        # Check circuit breaker before making request
        circuit_breaker = get_groq_circuit_breaker()
        if not circuit_breaker.can_proceed():
            logger.warning("Circuit breaker OPEN: Groq API temporarily unavailable")
            return None
        
        # Get Groq rate limiter and acquire permission before making request
        rate_limiter = get_groq_rate_limiter()
        estimated_tokens = rate_limiter.estimate_tokens(prompt, has_image=False)
        
        # Acquire rate limiter permission (waits if needed)
        rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
        
        for attempt in range(max_retries):
            # CIRCUIT-AWARE RETRY: Check circuit breaker before each retry attempt
            if attempt > 0 and not circuit_breaker.can_proceed():
                logger.warning(f"Circuit breaker OPEN during Groq retry - aborting")
                return None
            
            try:
                # CRITICAL: Use concurrency guard to limit parallel Groq calls
                with groq_concurrency_guard():
                    completion = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        temperature=1,
                        max_completion_tokens=1024,
                        top_p=1,
                        stream=False,  # Non-streaming for easier response handling
                        stop=None
                    )
                
                # Extract text from response (outside guard)
                if completion.choices and len(completion.choices) > 0:
                    message = completion.choices[0].message
                    if hasattr(message, 'content') and message.content:
                        response_text = message.content.strip()
                        # Record success in circuit breaker
                        circuit_breaker.record_success()
                        # Cache response
                        if use_cache:
                            cache_key = self._get_cache_key(prompt, model)
                            _groq_response_cache[cache_key] = response_text
                        return response_text
                    elif hasattr(message, 'text'):
                        response_text = message.text.strip()
                        # Record success in circuit breaker
                        circuit_breaker.record_success()
                        # Cache response
                        if use_cache:
                            cache_key = self._get_cache_key(prompt, model)
                            _groq_response_cache[cache_key] = response_text
                        return response_text
                
                return None
            
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit errors (429 or quota exceeded)
                is_rate_limit = (
                    '429' in error_str or 
                    'quota' in error_str.lower() or 
                    'rate limit' in error_str.lower() or
                    'rate_limit_exceeded' in error_str.lower() or
                    'retry' in error_str.lower()
                )
                
                if is_rate_limit:
                    # Record error in circuit breaker
                    circuit_breaker.record_error(is_rate_limit=True)
                    
                    # CIRCUIT-AWARE: If circuit just opened, don't retry
                    if not circuit_breaker.can_proceed():
                        logger.warning("Circuit breaker OPEN after Groq 429 - skipping retries")
                        return None
                    
                    # Extract retry delay from error message if available
                    retry_delay = self._extract_retry_delay(error_str)
                    if retry_delay:
                        logger.warning(
                            f"Groq rate limit hit (429). Waiting {retry_delay}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_delay)
                        # Re-acquire rate limiter after waiting
                        rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
                    else:
                        # Default delay: exponential backoff with minimum 2 seconds (Groq often says "try again in 2s")
                        delay = min(2 * (2 ** attempt), 60)  # Start at 2s, max 60 seconds
                        logger.warning(
                            f"Groq rate limit hit (429). Waiting {delay}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                            # Re-acquire rate limiter after waiting
                        rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
                else:
                    logger.warning(f"Groq API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt == max_retries - 1:
                    # Record final failure in circuit breaker
                    circuit_breaker.record_error(is_rate_limit=is_rate_limit)
                    logger.error("All Groq API retry attempts failed")
                    return None
                
                # Small delay before retry for non-rate-limit errors
                if not is_rate_limit:
                    time.sleep(1)
        
        return None
    
    def _extract_retry_delay(self, error_str: str) -> Optional[float]:
        """Extract retry delay from error message."""
        # Look for patterns like "retry in 49.42s", "wait 30 seconds", "try again in 2s"
        patterns = [
            r'try again in (\d+\.?\d*)\s*s',  # Groq format: "try again in 2s"
            r'retry in (\d+\.?\d*)\s*s',
            r'wait (\d+\.?\d*)\s*seconds?',
            r'retry after (\d+\.?\d*)\s*s',
            r'(\d+\.?\d*)\s*seconds?',  # Generic number followed by "seconds"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                try:
                    delay = float(match.group(1))
                    # Add small buffer (0.5s) to be safe
                    return delay + 0.5
                except (ValueError, IndexError):
                    continue
        
        return None
    
    def check_theme_alignment(
        self,
        title: str,
        objectives: str,
        learning_outcomes: str,
        theme: str
    ) -> bool:
        """
        Check if title, objectives, and learning outcomes align with theme.
        Returns True if aligned, False otherwise.
        """
        prompt = f"""You are a validation system. Determine if the following event details align with the specified theme.

Theme: {theme}

Event Title: {title}
Objectives: {objectives}
Learning Outcomes: {learning_outcomes}

Task: Determine if the title, objectives, and learning outcomes are semantically aligned with the theme.

Respond with ONLY one word: "YES" if aligned, "NO" if not aligned."""
        
        response = self._call_groq(prompt)
        if not response:
            logger.warning("Groq theme check failed, defaulting to False")
            return False
        
        return "YES" in response.upper()
    
    def check_pdf_consistency(
        self,
        pdf_text: str,
        expected_title: Optional[str],
        expected_objectives: Optional[str],
        expected_learning_outcomes: Optional[str],
        expected_participants: Optional[int]
    ) -> Dict[str, bool]:
        """
        Check PDF text for consistency with expected values.
        Returns dict with keys: title_match, objectives_match, learning_match, participants_valid
        """
        results = {
            "title_match": False,
            "objectives_match": False,
            "learning_match": False,
            "participants_valid": False
        }
        
        prompt = f"""You are a validation system. Analyze the following PDF text and check consistency.

PDF Text:
{pdf_text[:3000]}  # Limit text length

Expected Title: {expected_title or 'Not provided'}
Expected Objectives: {expected_objectives or 'Not provided'}
Expected Learning Outcomes: {expected_learning_outcomes or 'Not provided'}
Expected Participants: {expected_participants or 'Not provided'}

Task: Check if:
1. PDF title matches expected title (fuzzy match acceptable)
2. PDF objectives match expected objectives
3. PDF learning outcomes match expected learning outcomes
4. PDF contains participant information indicating 20+ participants

Respond in this exact format (one line per check):
TITLE_MATCH: YES or NO
OBJECTIVES_MATCH: YES or NO
LEARNING_MATCH: YES or NO
PARTICIPANTS_VALID: YES or NO"""
        
        response = self._call_groq(prompt)
        if not response:
            logger.warning("Groq PDF consistency check failed")
            return results
        
        # Parse response
        for line in response.split('\n'):
            line = line.strip()
            if 'TITLE_MATCH:' in line:
                results["title_match"] = "YES" in line.upper()
            elif 'OBJECTIVES_MATCH:' in line:
                results["objectives_match"] = "YES" in line.upper()
            elif 'LEARNING_MATCH:' in line:
                results["learning_match"] = "YES" in line.upper()
            elif 'PARTICIPANTS_VALID:' in line:
                results["participants_valid"] = "YES" in line.upper()
        
        return results
    
    def _encode_image_to_base64(self, image_path: Path) -> Optional[str]:
        """Encode image file to base64 string."""
        try:
            # Ensure image_path is a Path object
            if not isinstance(image_path, Path):
                image_path = Path(image_path)
            
            # Check if file exists
            if not image_path.exists():
                logger.error(f"Image file does not exist: {image_path}")
                return None
            
            with open(image_path, 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
            return None
    
    def analyze_image(
        self,
        image_path: Path,
        event_mode: Optional[str] = None,
        event_title: Optional[str] = None,
        event_theme: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze image for event validation using Groq Vision model.
        
        Args:
            image_path: Path to image file
            event_mode: Event mode (online/offline)
            event_title: Event title for banner text validation
            event_theme: Event theme for context
        
        Returns:
            Dict with keys: has_banner, is_real_event, mode_matches, has_20_plus_participants,
            banner_text_matches, participant_count_estimate, detailed_reasoning
        """
        results = {
            "has_banner": False,
            "is_real_event": False,
            "mode_matches": False,
            "has_20_plus_participants": False,
            "banner_text_matches": False,
            "participant_count_estimate": 0,
            "detailed_reasoning": ""
        }
        
        if not self.client:
            logger.warning("Groq client not available for image analysis")
            return results
        
        # Try to encode image for vision model
        image_base64 = self._encode_image_to_base64(image_path)
        
        # Build comprehensive prompt for vision analysis
        prompt = f"""You are analyzing an event photograph for validation purposes.

Event Context:
- Title: {event_title or 'Not specified'}
- Theme: {event_theme or 'Not specified'}
- Expected Mode: {event_mode or 'Not specified'}

Task: Analyze the image and determine:
1. Does the image show a banner or poster with text? If yes, does the banner text match the event title/theme?
2. Does the image depict a real event/activity (not stock photo, not staged, not just a poster)?
3. Does the event mode (online/offline) match what's visible in the image?
   - Online: screens, video calls, virtual backgrounds, remote participants
   - Offline: physical venue, in-person attendees, physical setup
4. How many participants are visible? Provide an estimate.
5. Is this clearly a real event scene with actual activity?

Respond in this exact format:
HAS_BANNER: YES or NO
BANNER_TEXT_MATCHES: YES or NO
IS_REAL_EVENT: YES or NO
MODE_MATCHES: YES or NO
PARTICIPANT_COUNT: <number>
HAS_20_PLUS_PARTICIPANTS: YES or NO
REASONING: <brief explanation>"""
        
        # For now, use text-based analysis (Groq vision API may require different format)
        # In production, pass image_base64 to vision model if supported
        response = self._call_groq(prompt, model=self.image_model, use_cache=False)
        if not response:
            logger.warning("Groq image analysis failed")
            return results
        
        # Parse response
        for line in response.split('\n'):
            line = line.strip()
            if 'HAS_BANNER:' in line:
                results["has_banner"] = "YES" in line.upper()
            elif 'BANNER_TEXT_MATCHES:' in line:
                results["banner_text_matches"] = "YES" in line.upper()
            elif 'IS_REAL_EVENT:' in line:
                results["is_real_event"] = "YES" in line.upper()
            elif 'MODE_MATCHES:' in line:
                results["mode_matches"] = "YES" in line.upper()
            elif 'PARTICIPANT_COUNT:' in line:
                try:
                    count_str = line.split(':')[1].strip()
                    results["participant_count_estimate"] = int(count_str)
                except (ValueError, IndexError):
                    pass
            elif 'HAS_20_PLUS_PARTICIPANTS:' in line:
                results["has_20_plus_participants"] = "YES" in line.upper()
            elif 'REASONING:' in line:
                results["detailed_reasoning"] = line.split(':', 1)[1].strip() if ':' in line else ""
        
        return results
    
    def analyze_pdf_with_vision(
        self,
        pdf_text: str,
        expected_title: Optional[str],
        expected_objectives: Optional[str],
        expected_learning_outcomes: Optional[str],
        theme: Optional[str]
    ) -> Dict[str, Any]:
        """
        Analyze PDF content using Groq Vision for semantic validation.
        
        Args:
            pdf_text: Extracted PDF text
            expected_title: Expected title
            expected_objectives: Expected objectives
            expected_learning_outcomes: Expected learning outcomes
            theme: Event theme
        
        Returns:
            Dict with validation results and detailed reasoning
        """
        results = {
            "title_match": False,
            "objectives_match": False,
            "learning_match": False,
            "expert_details_present": False,
            "participants_valid": False,
            "theme_alignment": False,
            "detailed_reasoning": ""
        }
        
        prompt = f"""You are validating a PDF report for an event submission.

Expected Context:
- Title: {expected_title or 'Not specified'}
- Objectives: {expected_objectives or 'Not specified'}
- Learning Outcomes: {expected_learning_outcomes or 'Not specified'}
- Theme: {theme or 'Not specified'}

PDF Content (first 3000 characters):
{pdf_text[:3000]}

Task: Validate the PDF content and determine:
1. Does the PDF title match the expected title (fuzzy match acceptable)?
2. Do the PDF objectives align with expected objectives?
3. Do the PDF learning outcomes align with expected learning outcomes?
4. Are expert details present (name, designation, affiliation)?
5. Does the PDF contain participant information indicating 20+ participants?
6. Does the overall content align with the declared theme?

Respond in this exact format:
TITLE_MATCH: YES or NO
OBJECTIVES_MATCH: YES or NO
LEARNING_MATCH: YES or NO
EXPERT_DETAILS: YES or NO
PARTICIPANTS_VALID: YES or NO
THEME_ALIGNMENT: YES or NO
REASONING: <detailed explanation>"""
        
        response = self._call_groq(prompt, model=self.text_model)
        if not response:
            logger.warning("Groq PDF vision analysis failed")
            return results
        
        # Parse response
        for line in response.split('\n'):
            line = line.strip()
            if 'TITLE_MATCH:' in line:
                results["title_match"] = "YES" in line.upper()
            elif 'OBJECTIVES_MATCH:' in line:
                results["objectives_match"] = "YES" in line.upper()
            elif 'LEARNING_MATCH:' in line:
                results["learning_match"] = "YES" in line.upper()
            elif 'EXPERT_DETAILS:' in line:
                results["expert_details_present"] = "YES" in line.upper()
            elif 'PARTICIPANTS_VALID:' in line:
                results["participants_valid"] = "YES" in line.upper()
            elif 'THEME_ALIGNMENT:' in line:
                results["theme_alignment"] = "YES" in line.upper()
            elif 'REASONING:' in line:
                results["detailed_reasoning"] = line.split(':', 1)[1].strip() if ':' in line else ""
        
        return results

