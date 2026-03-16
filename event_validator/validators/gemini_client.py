"""Gemini API client for semantic validation with vision support. Falls back to Groq on failure."""
import logging
from typing import Optional, Dict, Any, Callable
import os
import time
import re
import json
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from dotenv import load_dotenv
from event_validator.utils.rate_limiter import get_rate_limiter
from event_validator.utils.circuit_breaker import get_gemini_circuit_breaker
from event_validator.utils.concurrency import gemini_concurrency_guard

# Load environment variables from .env file
load_dotenv()

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    GENAI_AVAILABLE = False

# Import GroqClient for fallback
try:
    from event_validator.validators.groq_client import GroqClient
    GROQ_AVAILABLE = True
except ImportError:
    GroqClient = None
    GROQ_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global cache for Gemini API responses (keyed by content hash)
# Cache structure: {cache_key: response_text}
_gemini_response_cache: Dict[str, str] = {}
# Cache for parsed validation results (to avoid re-parsing)
_gemini_parsed_cache: Dict[str, Dict[str, Any]] = {}

# Callback function to signal rate limit detection (set by app.py)
_rate_limit_callback: Optional[Callable[[], None]] = None

def set_rate_limit_callback(callback: Callable[[], None]):
    """Set a callback function to be called when rate limit is detected."""
    global _rate_limit_callback
    _rate_limit_callback = callback


class GeminiClient:
    """Client for interacting with Gemini models - optimized for performance and cost."""
    
    def __init__(self, api_key: Optional[str] = None, groq_api_key: Optional[str] = None):
        """Initialize Gemini client with optimal models. Falls back to Groq if Gemini fails."""
        # Initialize model names first (always set, even if client fails)
        # Fallback chain: flash → flash-lite → pro → Groq
        self.text_model = "gemini-2.5-flash"
        self.vision_model = "gemini-2.5-flash"
        # Ordered fallback list: [(text_model, vision_model, max_retries), ...]
        self.gemini_fallbacks = [
            ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite", 2),  # Fallback 1: cheapest/fastest
            ("gemini-2.5-pro", "gemini-2.5-pro", 1),                # Fallback 2: most capable
        ]
        
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        
        # Initialize Gemini client
        if not self.api_key:
            logger.warning("Gemini API key not provided. Set GEMINI_API_KEY environment variable.")
            self.client = None
        elif not GENAI_AVAILABLE:
            logger.error("google-genai package not installed. Install with: pip install google-genai")
            self.client = None
        else:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Gemini client initialized. Primary: {self.text_model}, Fallbacks: {[f[0] for f in self.gemini_fallbacks]}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.client = None
        
        # Initialize Groq client as fallback
        self.groq_client = None
        if GROQ_AVAILABLE and GroqClient:
            groq_key = groq_api_key or os.getenv("GROQ_API_KEY") or os.getenv("GROQ_CLOUD_API")
            if groq_key:
                try:
                    self.groq_client = GroqClient(api_key=groq_key)
                    if self.groq_client.client:
                        logger.info(f"Groq fallback client initialized. Text model: {self.groq_client.text_model}, Image model: {self.groq_client.image_model}")
                    else:
                        logger.warning("Groq fallback client created but not available (missing API key or package)")
                except Exception as e:
                    logger.warning(f"Failed to initialize Groq fallback client: {e}")
                    self.groq_client = None
            else:
                logger.debug("Groq API key not provided for fallback")
        else:
            logger.debug("Groq package not available for fallback")
    
    def _get_next_gemini_fallback(self, fallback_level: int, image_path: Optional[Path] = None):
        """Get the next fallback Gemini model and its retry count.

        Returns:
            (model_name, max_retries, next_level) or (None, 0, level) if no more fallbacks.
        """
        if fallback_level < len(self.gemini_fallbacks):
            text_model, vision_model, max_retries = self.gemini_fallbacks[fallback_level]
            model = vision_model if image_path else text_model
            return model, max_retries, fallback_level + 1
        return None, 0, fallback_level + 1

    def _get_cache_key(self, prompt: str, model: Optional[str] = None, image_hash: Optional[str] = None, pdf_hash: Optional[str] = None) -> str:
        """Generate cache key for prompt, model, and optionally image/pdf hash."""
        content = f"{model or self.text_model}:{prompt}"
        if image_hash:
            content += f":img:{image_hash}"
        if pdf_hash:
            content += f":pdf:{pdf_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _call_gemini(
        self,
        prompt: str,
        model: Optional[str] = None,
        image_path: Optional[Path] = None,
        max_retries: int = 3,
        use_cache: bool = True,
        _fallback_level: int = 0
    ) -> Optional[str]:
        """
        Call Gemini API with retry logic, rate limit handling, and caching.
        Fallback chain: gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.5-pro → Groq.

        Args:
            prompt: Prompt text
            model: Model name (defaults to text_model for text, vision_model for images)
            image_path: Optional path to image file for vision tasks
            max_retries: Maximum retry attempts
            use_cache: Whether to use response cache
            _fallback_level: Internal counter tracking which Gemini fallback to try next

        Returns:
            Response text or None if failed
        """
        # If Gemini client not available, try Groq fallback immediately (last resort)
        if not self.client:
            logger.debug("Gemini client not available, trying Groq fallback as last resort...")
            if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                # For text-only calls, Groq can handle it directly
                if not image_path:
                    groq_response = self.groq_client._call_groq(prompt, use_cache=use_cache)
                    if groq_response:
                        logger.info("Groq fallback succeeded for text call")
                        return groq_response
                logger.debug("Groq fallback not suitable for this call type")
            return None
        
        # Determine model based on whether image is provided
        if image_path:
            model = model or self.vision_model
        else:
            model = model or self.text_model
        
        # Check cache first (with content hash for deterministic caching)
        image_hash = None
        if image_path and image_path.exists():
            # Compute image hash for cache key (use SHA256 for better cache hits)
            try:
                from event_validator.utils.hashing import compute_sha256
                image_hash = compute_sha256(image_path)
            except Exception as e:
                logger.debug(f"Could not compute image hash for caching: {e}")
                # Fallback to MD5 if SHA256 fails
                try:
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                        image_hash = hashlib.md5(image_data).hexdigest()
                except Exception:
                    pass
        
        if use_cache and image_hash:
            cache_key = self._get_cache_key(prompt, model, image_hash=image_hash[:16])
            if cache_key in _gemini_response_cache:
                logger.debug(f"Cache hit for image analysis (model: {model})")
                return _gemini_response_cache[cache_key]
        elif use_cache and not image_path:
            # Text-only call, check cache
            cache_key = self._get_cache_key(prompt, model)
            if cache_key in _gemini_response_cache:
                logger.debug(f"Cache hit for text prompt (model: {model})")
                return _gemini_response_cache[cache_key]
        
        # Check circuit breaker before making request
        circuit_breaker = get_gemini_circuit_breaker()
        if not circuit_breaker.can_proceed():
            logger.warning("Circuit breaker OPEN: Gemini API temporarily unavailable")
            # Try next Gemini fallback model
            fallback_model, fb_retries, next_level = self._get_next_gemini_fallback(_fallback_level, image_path)
            if fallback_model and self.client:
                logger.info(f"Trying Gemini fallback model {fallback_model} due to circuit breaker")
                fallback_result = self._call_gemini(
                    prompt, model=fallback_model, image_path=image_path,
                    max_retries=fb_retries, use_cache=use_cache, _fallback_level=next_level
                )
                if fallback_result:
                    return fallback_result
            # Try Groq as last resort
            if self.groq_client and hasattr(self.groq_client, '_call_groq') and not image_path:
                logger.info("Attempting Groq fallback due to Gemini circuit breaker")
                groq_response = self.groq_client._call_groq(prompt, use_cache=use_cache)
                if groq_response:
                    return groq_response
            return None
        
        # Note: Removed fixed 5-second delay - rate limiter handles spacing automatically
        # With 120 RPM (80% of 150), rate limiter enforces proper spacing (0.5s minimum between requests)
        
        # Use smart rate limiter with token-aware delays
        # This calculates the exact delay needed based on recent request history and token count
        rate_limiter = get_rate_limiter()
        estimated_tokens = rate_limiter.estimate_tokens(prompt, has_image=(image_path is not None))
        delay = rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
        if delay > 0:
            logger.debug(f"Rate limiter applied additional {delay:.2f}s delay (current rate: {rate_limiter.get_current_rate():.1f} RPM, tokens: ~{estimated_tokens})")
        
        for attempt in range(max_retries):
            # CIRCUIT-AWARE RETRY: Check circuit breaker before each retry attempt
            if attempt > 0 and not circuit_breaker.can_proceed():
                logger.warning(f"Circuit breaker OPEN during retry - aborting Gemini retries")
                # Try next Gemini fallback model
                fallback_model, fb_retries, next_level = self._get_next_gemini_fallback(_fallback_level, image_path)
                if fallback_model and self.client:
                    logger.info(f"Trying Gemini fallback model {fallback_model} (mid-retry circuit break)")
                    fallback_result = self._call_gemini(
                        prompt, model=fallback_model, image_path=image_path,
                        max_retries=fb_retries, use_cache=use_cache, _fallback_level=next_level
                    )
                    if fallback_result:
                        return fallback_result
                # Try Groq as last resort
                if self.groq_client and hasattr(self.groq_client, '_call_groq') and not image_path:
                    logger.info("Attempting Groq fallback due to circuit breaker (mid-retry)")
                    groq_response = self.groq_client._call_groq(prompt, use_cache=use_cache)
                    if groq_response:
                        return groq_response
                return None
            
            try:
                # CRITICAL: Use concurrency semaphore to limit parallel Gemini calls
                # This prevents burst 429s even with multiple workers
                with gemini_concurrency_guard():
                    # No additional delay needed here - already applied before rate limiter
                    
                    # Prepare content parts
                    parts = [types.Part.from_text(text=prompt)]
                    
                    # Add image if provided
                    if image_path and image_path.exists():
                        with open(image_path, 'rb') as image_file:
                            image_data = image_file.read()
                        
                        # Determine MIME type from file extension
                        image_ext = image_path.suffix.lower()
                        mime_type_map = {
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.png': 'image/png',
                            '.gif': 'image/gif',
                            '.webp': 'image/webp'
                        }
                        mime_type = mime_type_map.get(image_ext, 'image/jpeg')
                        
                        parts.append(types.Part.from_bytes(data=image_data, mime_type=mime_type))
                    
                    contents = [types.Content(role="user", parts=parts)]
                    
                    response = self.client.models.generate_content(
                        model=model,
                        contents=contents,
                    )
                
                # Extract text from response (outside semaphore)
                response_text = ""
                if hasattr(response, 'text'):
                    response_text = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        response_parts = candidate.content.parts
                        if response_parts and hasattr(response_parts[0], 'text'):
                            response_text = response_parts[0].text
                
                if response_text:
                    response_text = response_text.strip()
                    # Record success in circuit breaker
                    circuit_breaker.record_success()
                    # Cache response
                    if use_cache:
                        cache_key = self._get_cache_key(prompt, model, image_hash)
                        _gemini_response_cache[cache_key] = response_text
                        logger.debug(f"Cached response with key: {cache_key[:16]}...")
                    return response_text
                
                return None
                
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit errors (429 or quota exceeded)
                is_rate_limit = (
                    '429' in error_str or 
                    'quota' in error_str.lower() or 
                    'rate limit' in error_str.lower() or
                    'retry' in error_str.lower() or
                    'resource_exhausted' in error_str.lower()
                )
                
                if is_rate_limit:
                    # Record error in circuit breaker
                    circuit_breaker.record_error(is_rate_limit=True)
                    
                    # CIRCUIT-AWARE: If circuit just opened, don't retry - fallback immediately
                    if not circuit_breaker.can_proceed():
                        logger.warning("Circuit breaker OPEN after 429 - skipping retries, falling back")
                        # Try next Gemini fallback model
                        fallback_model, fb_retries, next_level = self._get_next_gemini_fallback(_fallback_level, image_path)
                        if fallback_model and self.client:
                            logger.info(f"Trying Gemini fallback model {fallback_model} after 429 circuit break")
                            fallback_result = self._call_gemini(
                                prompt, model=fallback_model, image_path=image_path,
                                max_retries=fb_retries, use_cache=use_cache, _fallback_level=next_level
                            )
                            if fallback_result:
                                return fallback_result
                        # Try Groq as last resort
                        if self.groq_client and hasattr(self.groq_client, '_call_groq') and not image_path:
                            groq_response = self.groq_client._call_groq(prompt, use_cache=use_cache)
                            if groq_response:
                                return groq_response
                        return None
                    
                    # Signal rate limit detection to app.py
                    if _rate_limit_callback:
                        try:
                            _rate_limit_callback()
                        except Exception as cb_error:
                            logger.warning(f"Rate limit callback failed: {cb_error}")
                    
                    # Extract retry delay from error message if available
                    retry_delay = self._extract_retry_delay(error_str)
                    if retry_delay:
                        # Use extracted delay, but ensure minimum 5 seconds
                        delay = max(retry_delay, 5.0)
                        logger.warning(
                            f"Rate limit hit. Waiting {delay:.1f}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                    else:
                        # Exponential backoff: base * (2^attempt), max 60 seconds
                        base_delay = 2.0  # Start at 2s for Gemini
                        delay = min(base_delay * (2 ** attempt), 60)
                        logger.warning(
                            f"Rate limit hit. Waiting {delay:.1f}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                    
                    # Re-acquire rate limiter after waiting
                    rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
                else:
                    logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    # Small delay before retry for non-rate-limit errors
                    time.sleep(1)
                
                # Only try fallbacks after all retries for current model fail
                if attempt == max_retries - 1:
                    # Step 1: Try next Gemini fallback model
                    fallback_model, fb_retries, next_level = self._get_next_gemini_fallback(_fallback_level, image_path)
                    if fallback_model and self.client:
                        logger.warning(
                            f"Gemini model {model} failed after {max_retries} retries. "
                            f"Trying fallback Gemini model: {fallback_model}"
                        )
                        fallback_result = self._call_gemini(
                            prompt,
                            model=fallback_model,
                            image_path=image_path,
                            max_retries=fb_retries,
                            use_cache=use_cache,
                            _fallback_level=next_level
                        )
                        if fallback_result:
                            return fallback_result
                        logger.warning(f"Gemini fallback model {fallback_model} also failed")

                    # Step 2: Try Groq as last resort
                    logger.warning("All Gemini models failed, trying Groq as last resort...")
                    if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                        logger.info("Falling back to Groq API as last resort")
                        if image_path:
                            logger.warning("Groq fallback for image analysis may have limited capabilities")
                            try:
                                groq_response = self.groq_client._call_groq(prompt, model=self.groq_client.image_model, use_cache=use_cache)
                                if groq_response:
                                    logger.info("Groq fallback succeeded for image analysis")
                                    return groq_response
                            except Exception as e:
                                logger.warning(f"Groq fallback for image analysis failed: {e}")
                        else:
                            try:
                                groq_response = self.groq_client._call_groq(prompt, model=self.groq_client.text_model, use_cache=use_cache)
                                if groq_response:
                                    logger.info("Groq fallback succeeded for text call")
                                    return groq_response
                            except Exception as e:
                                logger.warning(f"Groq fallback for text call failed: {e}")

                    logger.error("All API calls failed (Gemini primary + fallbacks + Groq)")
                    return None

        return None

    def _extract_retry_delay(self, error_str: str) -> Optional[float]:
        """Extract retry delay from error message."""
        # Look for patterns like "retry_delay { seconds: 49 }" or "retry in 49.42s"
        patterns = [
            r'retry_delay\s*\{\s*seconds:\s*(\d+)',
            r'retry in (\d+\.?\d*)\s*s',
            r'wait (\d+\.?\d*)\s*seconds?',
            r'retry after (\d+\.?\d*)\s*s',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        return None

    def check_theme_alignment(
        self,
        title: str,
        objectives: str,
        learning_outcomes: str,
        theme: str,
        prefer_groq: bool = False
    ) -> bool:
        """
        Check if title, objectives, and learning outcomes align with theme.
        Returns True if aligned, False otherwise.
        
        REDEFINED: Purely semantic check using LLM. Redundant Python filters removed.
        """
        prompt = f"""You are a strict Innovation Auditor.
        Determine if the following Event Activity is a VALID Innovation/Design Thinking/Entrepreneurship initiative.

        Theme: {theme}
        Activity Name: {title}
        Objectives: {objectives[:300]}
        Learning Outcomes: {learning_outcomes[:300]}

        RULES:
        1. ACCEPT: Workshops on "Design Thinking", "Critical Thinking", "Problem Solving", "Entrepreneurship", or "Startups" applied to technical or business fields.
        2. REJECT: Generic academic lectures, scientific seminars, or technical skill training (e.g. Java, Python) without a clear innovation/business outcome.
        3. REJECT: General awareness, celebrations, or orientation sessions.

        OUTPUT FORMAT:
        RESULT: [YES or NO]
        REASON: [Short 1-sentence explanation]
        """
        
        # Primary: Try Gemini first
        response = self._call_gemini(prompt, use_cache=True)
        if response:
            return "YES" in response.upper() or "RESULT: YES" in response.upper()
        
        # Fallback: If Gemini fails, try both Gemini retry and Groq simultaneously
        logger.warning("Gemini theme alignment failed, attempting parallel fallback (Gemini retry + Groq)")
        
        def try_gemini_retry() -> Optional[str]:
            """Retry Gemini call."""
            try:
                return self._call_gemini(prompt, use_cache=False)  # Don't use cache on retry
            except Exception as e:
                logger.debug(f"Gemini retry failed: {e}")
                return None
        
        def try_groq() -> Optional[bool]:
            """Try Groq as fallback."""
            if not self.groq_client or not hasattr(self.groq_client, 'check_theme_alignment'):
                return None
            try:
                logger.debug("Trying Groq as parallel fallback")
                return self.groq_client.check_theme_alignment(title, objectives, learning_outcomes, theme)
            except Exception as e:
                logger.debug(f"Groq fallback failed: {e}")
                return None
        
        # Execute both fallbacks in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(try_gemini_retry): 'gemini',
                executor.submit(try_groq): 'groq'
            }
            
            # Wait for first successful response
            for future in as_completed(futures):
                source = futures[future]
                try:
                    result = future.result(timeout=30)  # 30 second timeout per call
                    if result is not None:
                        if source == 'gemini':
                            # Gemini returns string response
                            if isinstance(result, str) and result:
                                aligned = "YES" in result.upper()
                                logger.info(f"Theme alignment: Gemini retry succeeded")
                                return aligned
                        elif source == 'groq':
                            # Groq returns boolean directly
                            if isinstance(result, bool):
                                logger.info(f"Theme alignment: Groq fallback succeeded")
                                return result
                except Exception as e:
                    logger.debug(f"Fallback call from {source} failed: {e}")
                    continue
        
        # If all fallbacks failed
        logger.warning("All theme alignment checks failed (Gemini primary, Gemini retry, Groq fallback), defaulting to False")
        return False
    
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
1. PDF title matches expected title (SIMILARITY IS ACCEPTABLE - exact match not required. Accept if titles are semantically similar, have similar meaning, or contain key words from expected title. Minor variations in wording, word order, or formatting are acceptable.)
2. PDF objectives match expected objectives
3. PDF learning outcomes match expected learning outcomes
4. PDF contains participant information indicating 15+ participants

Respond in this exact format (one line per check):
TITLE_MATCH: YES or NO
OBJECTIVES_MATCH: YES or NO
LEARNING_MATCH: YES or NO
PARTICIPANTS_VALID: YES or NO"""
        
        response = self._call_gemini(prompt)
        if not response:
            logger.warning("PDF consistency check failed (Gemini and Groq fallback)")
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
    
    def check_pdf_relevance(
        self,
        pdf_text: str,
        activity_name: str
    ) -> bool:
        """
        Check if the activity name is broadly relevant to the PDF content.
        Uses ONLY the first page of the PDF for efficiency and accuracy.
        This is Flow 2 of the redefined validation logic.
        """
        # Extract first page only using form-feed delimiter
        first_page = pdf_text
        if '\f' in pdf_text:
            first_page = pdf_text.split('\f')[0]
        elif '\n\n\n' in pdf_text:
            first_page = pdf_text.split('\n\n\n')[0]
        
        # Fallback: cap at 2000 chars if no page break found
        if len(first_page) > 2000:
            first_page = first_page[:2000]
        
        prompt = f"""You are a lenient document reviewer. Your job is to check if a PDF report is BROADLY RELATED to an event activity.

Activity Name: {activity_name}

PDF First Page Content:
{first_page}

RULES:
1. Answer YES if the PDF content is about the SAME GENERAL TOPIC or subject area as the activity name.
2. Answer YES even if the exact wording differs — synonyms, paraphrases, and related sub-topics all count as relevant.
3. Answer NO ONLY if the PDF is about a COMPLETELY DIFFERENT and UNRELATED subject (e.g., activity is about "Entrepreneurship" but PDF is about "Yoga Day").
4. When in doubt, answer YES.

OUTPUT FORMAT:
RESULT: [YES or NO]
REASON: [Short 1-sentence explanation]
"""
        
        response = self._call_gemini(prompt, use_cache=True)
        if response:
            return "RESULT: YES" in response.upper() or ("YES" in response.upper() and "RESULT: NO" not in response.upper())
        
        # Default to True (lenient) if LLM fails
        return True
    
    def validate_pdf_comprehensive(
        self,
        pdf_text: str,
        expected_title: Optional[str],
        expected_objectives: Optional[str],
        expected_learning_outcomes: Optional[str],
        expected_participants: Optional[int],
        pdf_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        OPTIMIZED: Single unified PDF validation call that checks all 5 PDF rules at once.
        This replaces 5 separate API calls with 1 call, providing ~3-4x speedup.
        
        Returns dict with keys:
        - title_match: bool
        - expert_details_present: bool
        - learning_outcomes_align: bool
        - objectives_match: bool
        - participants_valid: bool
        - reasoning: str
        """
        # Generate cache key using PDF content hash if provided
        cache_key = None
        if pdf_hash:
            cache_key = self._get_cache_key(
                f"pdf_validation:{expected_title}:{expected_objectives}:{expected_learning_outcomes}:{expected_participants or 15}",
                model=self.text_model,
                pdf_hash=pdf_hash
            )
            # Check cache first (both raw response and parsed results)
            if cache_key in _gemini_parsed_cache:
                logger.debug("PDF validation cache hit (parsed results)")
                return _gemini_parsed_cache[cache_key]
            elif cache_key in _gemini_response_cache:
                logger.debug("PDF validation cache hit (raw response)")
                cached_response = _gemini_response_cache[cache_key]
                parsed_results = self._parse_pdf_validation_response(cached_response)
                _gemini_parsed_cache[cache_key] = parsed_results
                return parsed_results
        
        results = {
            "title_match": False,
            "expert_details_present": False,
            "learning_outcomes_align": False,
            "objectives_match": False,
            "participants_valid": False,
            "reasoning": ""
        }
        
        # Single comprehensive prompt for all PDF validations
        prompt = f"""You are validating a PDF report for an event submission. Analyze the PDF text and return ALL validation results in a single response.

PDF Text (first 4000 characters):
{pdf_text[:4000]}

Expected Metadata:
- Title: {expected_title or 'Not specified'}
- Objectives: {expected_objectives or 'Not specified'}
- Learning Outcomes: {expected_learning_outcomes or 'Not specified'}
- Expected Participants: {expected_participants or 'Not specified (needs 15+)'}

Task: Validate ALL of the following in ONE analysis:
1. Does the PDF title match the expected title? (SIMILARITY IS ACCEPTABLE - exact match not required. Accept if titles are semantically similar, have similar meaning, or contain key words from expected title. Minor variations in wording, word order, or formatting are acceptable.)
2. Are expert details present? (Look for: expert name, designation, affiliation, speaker, facilitator, resource person, keynote speaker, presenter)
3. Do the learning outcomes in the PDF align with the expected learning outcomes? (semantic alignment)
4. Do the objectives in the PDF match the expected objectives? (semantic alignment)
5. Does the PDF contain participant information indicating {expected_participants or 15}+ participants? (Look for participant count, attendance, number of attendees)

Respond in this EXACT format (one line per check):
TITLE_MATCH: YES or NO
EXPERT_DETAILS: YES or NO
LEARNING_OUTCOMES_ALIGN: YES or NO
OBJECTIVES_MATCH: YES or NO
PARTICIPANTS_VALID: YES or NO
REASONING: <brief explanation of your findings>"""
        
        response = self._call_gemini(prompt, use_cache=True)
        if not response:
            logger.warning("Comprehensive PDF validation failed (Gemini and Groq fallback)")
            return results
        
        # Parse and cache the response
        parsed_results = self._parse_pdf_validation_response(response)
        if cache_key:
            _gemini_response_cache[cache_key] = response
            _gemini_parsed_cache[cache_key] = parsed_results
            logger.debug(f"Cached PDF validation results with key: {cache_key[:16]}...")
        
        return parsed_results
    
    def _parse_pdf_validation_response(self, response: str) -> Dict[str, Any]:
        """Parse the unified PDF validation response."""
        results = {
            "title_match": False,
            "expert_details_present": False,
            "learning_outcomes_align": False,
            "objectives_match": False,
            "participants_valid": False,
            "reasoning": ""
        }
        
        for line in response.split('\n'):
            line = line.strip()
            if 'TITLE_MATCH:' in line:
                results["title_match"] = "YES" in line.upper()
            elif 'EXPERT_DETAILS:' in line:
                results["expert_details_present"] = "YES" in line.upper()
            elif 'LEARNING_OUTCOMES_ALIGN:' in line:
                results["learning_outcomes_align"] = "YES" in line.upper()
            elif 'OBJECTIVES_MATCH:' in line:
                results["objectives_match"] = "YES" in line.upper()
            elif 'PARTICIPANTS_VALID:' in line:
                results["participants_valid"] = "YES" in line.upper()
            elif 'REASONING:' in line:
                results["reasoning"] = line.split(':', 1)[1].strip() if ':' in line else ""
        
        return results
    
    def analyze_image(
        self,
        image_path: Path,
        event_mode: Optional[str] = None,
        event_title: Optional[str] = None,
        event_theme: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze image for event validation using Gemini Vision model.
        Includes robust JSON parsing to handle various LLM output formats.
        
        Args:
            image_path: Path to image file (Path object)
            event_mode: Event mode (online/offline)
            event_title: Event title for banner text validation
            event_theme: Event theme for context
        
        Returns:
            Dict with keys: has_banner, is_real_event, mode_match, has_15_plus_participants,
            banner_text_matches, participant_count_estimate, detailed_reasoning
        """
        results = {
            "has_banner": False,
            "is_real_event": False,
            "mode_match": False,
            "has_15_plus_participants": False,
            "banner_text_matches": False,
            "participant_count_estimate": 0,
            "detailed_reasoning": ""
        }
        
        # Ensure image_path is a Path object
        if not isinstance(image_path, Path):
            image_path = Path(image_path)
        
        # Check if file exists
        if not image_path.exists():
            logger.error(f"Image file does not exist: {image_path}")
            return results
        
        # If Gemini client not available, try Groq fallback immediately
        if not self.client:
            logger.warning("Gemini client not available for image analysis, trying Groq fallback...")
            if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                try:
                    groq_results = self.groq_client.analyze_image(image_path, event_mode, event_title, event_theme)
                    if groq_results and any(groq_results.values()):
                        logger.info("Groq fallback succeeded for image analysis")
                        return groq_results
                except Exception as e:
                    logger.warning(f"Groq fallback for image analysis failed: {e}")
            logger.warning("Both Gemini and Groq clients unavailable for image analysis")
            return results
        
        # Build comprehensive prompt for vision analysis
        prompt = f"""You are analyzing an event photograph for validation system.
            Event Title: {event_title or 'Not specified'}
            Event Theme: {event_theme or 'Not specified'}
            Expected Mode: {event_mode or 'Not specified'}
            
            CHECKLIST:
            1. Is there a banner or poster visible? (Yes/No)
            2. Is this a real event scene (people, interaction) or just a static object/screenshot? (Real/Fake)
            3. Are there more than 15 participants visible? (Yes/No)
            4. Does the scene match a '{event_mode}' event (online vs offline)? (Yes/No)
            
            OUTPUT JSON ONLY (No markdown, no explanation outside JSON):
            {{
                "has_banner": true,
                "is_real_event": true,
                "has_15_plus_participants": true,  // Should be >= 15
                "mode_match": true,
                "description": "short description"
            }}"""
        
        response = self._call_gemini(prompt, image_path=image_path, use_cache=False)
        if not response:
            logger.warning("Gemini image analysis failed, trying Groq fallback...")
             # Fallback to Groq if available
            if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                 try:
                     groq_results = self.groq_client.analyze_image(image_path, event_mode, event_title, event_theme)
                     if groq_results:
                         return groq_results
                 except Exception as e:
                     logger.warning(f"Groq fallback failed: {e}")
            return results
        
        # Flatten response text to string first
        response_text = response if isinstance(response, str) else str(response)

        # Robust JSON Parsing
        try:
            json_str = response_text
            # Try to extract from markdown code blocks first
            if "```" in response_text:
                # Handle both ```json and just ```
                blocks = response_text.split("```")
                for block in blocks:
                    block = block.strip()
                    if block.startswith("json"):
                        block = block[4:].strip()
                    if block.startswith("{") and block.endswith("}"):
                        json_str = block
                        break
            
            # Fallback: find first { and last }
            if "{" in json_str:
                json_str = "{" + json_str.split("{", 1)[1].rsplit("}", 1)[0] + "}"
            
            # Clean up potential Python booleans/None to valid JSON
            json_str = json_str.replace("True", "true").replace("False", "false").replace("None", "null")
            
            # Load JSON
            try:
                parsed_result = json.loads(json_str)
                # Merge into default results
                results.update(parsed_result)
                results["detailed_reasoning"] = parsed_result.get("description", "")
                return results
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode failed: {e}. Raw response: {response_text[:100]}...")
            
        except Exception as e:
            logger.warning(f"Failed to parse image analysis JSON: {response_text[:100]}... Error: {e}")
            
        return results

    def extract_text_from_image(self, image_path: Path) -> Dict[str, Any]:
        """
        Extract text from an image using the vision model (OCR-like).
        Then check if event details (date, time, title, event type) are present.
        
        Returns:
            Dict with keys: extracted_text, has_event_details, event_details_found
        """
        result = {
            "extracted_text": "",
            "has_event_details": False,
            "event_details_found": [],
            "has_visual_geotag": False
        }
        
        if not self.client:
            return result
        
        # Ensure image_path is Path
        if not isinstance(image_path, Path):
            image_path = Path(image_path)
            
        if not image_path.exists():
            return result
            
        try:
            # OPTIMIZATION: Use EasyOCR (Method 1) of Vision Model
            # This is faster and more accurate for "GPS Map Camera" overlays
            try:
                from event_validator.utils.ocr import extract_visual_geotag
                has_ocr_geotag, ocr_text = extract_visual_geotag(str(image_path))
                
                if ocr_text and len(ocr_text.strip()) > 5:
                    extracted_text = ocr_text
                    logger.info(f"Using EasyOCR text for {Path(image_path).name} (Length: {len(extracted_text)})")
                    if has_ocr_geotag:
                        logger.info("EasyOCR detected visual geotag keywords.")
                else:
                    extracted_text = ""
            except Exception as e:
                 logger.warning(f"EasyOCR logic failed: {e}")
                 extracted_text = ""

            # Standard Gemini/Groq Fallback if EasyOCR yields nothing
            if not extracted_text:
                prompt = """Read ALL text visible in this image. Extract every word, number, date, and line of text you can see.
                
                OUTPUT: Return ONLY the extracted text, nothing else. If no text is visible, return "NO TEXT FOUND"."""
                
                response = self._call_gemini(prompt, image_path=image_path, use_cache=True)
                
                if not response:
                    return result
                    
                extracted_text = response.strip() if isinstance(response, str) else str(response).strip()

            result["extracted_text"] = extracted_text
            
            if not extracted_text or extracted_text.upper() == "NO TEXT FOUND":
                return result
            
            text_lower = extracted_text.lower()
            details_found = []
            
            # Check for date patterns (DD/MM/YYYY, DD-MM-YYYY, Month Day Year, etc.)
            date_patterns = [
                r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
                r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}',
                r'\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)',
                r'\d{1,2}(st|nd|rd|th)\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',
            ]
            for pattern in date_patterns:
                if re.search(pattern, text_lower):
                    details_found.append("date")
                    break
            
            # Check for time patterns (HH:MM, AM/PM)
            time_patterns = [
                r'\d{1,2}:\d{2}',
                r'\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)',
            ]
            for pattern in time_patterns:
                if re.search(pattern, text_lower):
                    details_found.append("time")
                    break
            
            # Check for event type keywords
            event_keywords = [
                'workshop', 'seminar', 'webinar', 'conference', 'symposium',
                'hackathon', 'bootcamp', 'session', 'lecture', 'summit',
                'training', 'orientation', 'inauguration', 'event', 'program',
                'programme', 'meet', 'fest', 'expo', 'competition',
                'guest lecture', 'field visit', 'industry visit',
            ]
            for kw in event_keywords:
                if kw in text_lower:
                    details_found.append(f"event_type:{kw}")
                    break
            
            # Check for venue/location keywords
            venue_keywords = [
                'hall', 'auditorium', 'room', 'lab', 'laboratory', 'campus',
                'building', 'block', 'floor', 'center', 'centre', 'venue',
                'college', 'university', 'institute', 'department',
            ]
            for kw in venue_keywords:
                if kw in text_lower:
                    details_found.append(f"venue:{kw}")
                    break
            
            # Check for title-like content (capitalized phrases, theme mentions)
            title_keywords = [
                'innovation', 'entrepreneurship', 'startup', 'design thinking',
                'iic', 'institution', 'council', 'theme', 'topic',
            ]
            for kw in title_keywords:
                if kw in text_lower:
                    details_found.append(f"title:{kw}")
                    break
            
            # Check for visual geotag indicators (GPS coordinates, map overlays)
            geotag_indicators = [
                r'lat\s*[:\.]?\s*\d+',
                r'long\s*[:\.]?\s*\d+',
                r'gps\s*map\s*camera',
                r'altitude',
                r'\d+\.\d+\s*,\s*\d+\.\d+',  # decimal coordinates
                r'\d+°\s*\d+\'?\s*\d+"?\s*[NSEW]',  # DMS coordinates
            ]
            for indicator in geotag_indicators:
                if re.search(indicator, text_lower):
                    details_found.append("visual_geotag")
                    break
            
            result["event_details_found"] = details_found
            # Pass if at least 1 event detail found
            result["has_event_details"] = len(details_found) >= 1
            result["has_visual_geotag"] = "visual_geotag" in details_found
            
            logger.info(f"Banner/Geotag text extraction: found {len(details_found)} details: {details_found}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting text from image {image_path}: {e}")
            return result
    
    def analyze_pdf_with_vision(
        self,
        pdf_text: str,
        expected_title: Optional[str],
        expected_objectives: Optional[str],
        expected_learning_outcomes: Optional[str],
        theme: Optional[str]
    ) -> Dict[str, Any]:
        """
        Analyze PDF content using Gemini for semantic validation.
        
        Args:
            pdf_text: Extracted PDF text
            expected_title: Expected title
            expected_objectives: Expected objectives
            expected_learning_outcomes: Expected learning outcomes
            theme: Event theme
        
        Returns:
            Dict with validation results and detailed reasoning
        """
        # Reuse existing robust method
        return self.validate_pdf_comprehensive(
            pdf_text=pdf_text,
            expected_title=expected_title,
            expected_objectives=expected_objectives,
            expected_learning_outcomes=expected_learning_outcomes,
            expected_participants=None # Or pass if available
        )
