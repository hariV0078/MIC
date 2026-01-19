"""Gemini API client for semantic validation with vision support. Falls back to Groq on failure."""
import logging
from typing import Optional, Dict, Any
import os
import time
import re
import hashlib
from pathlib import Path
from dotenv import load_dotenv

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
_gemini_response_cache: Dict[str, str] = {}


class GeminiClient:
    """Client for interacting with Gemini models - optimized for performance and cost."""
    
    def __init__(self, api_key: Optional[str] = None, groq_api_key: Optional[str] = None):
        """Initialize Gemini client with optimal models. Falls back to Groq if Gemini fails."""
        # Initialize model names first (always set, even if client fails)
        # Using gemini-2.0-flash-exp for text (fastest, cost-effective)
        # Using gemini-2.5-pro for vision (best quality for image analysis)
        self.text_model = "gemini-2.0-flash-exp"  # Fast text model, experimental but stable
        self.vision_model = "gemini-2.5-pro"  # Best quality for vision tasks
        
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
                logger.info(f"Gemini client initialized. Text model: {self.text_model}, Vision model: {self.vision_model}")
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
    
    def _get_cache_key(self, prompt: str, model: Optional[str] = None, image_hash: Optional[str] = None) -> str:
        """Generate cache key for prompt, model, and optionally image hash."""
        content = f"{model or self.text_model}:{prompt}"
        if image_hash:
            content += f":{image_hash}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _call_gemini(
        self,
        prompt: str,
        model: Optional[str] = None,
        image_path: Optional[Path] = None,
        max_retries: int = 3,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        Call Gemini API with retry logic, rate limit handling, and caching.
        Falls back to Groq if Gemini is unavailable or fails.
        
        Args:
            prompt: Prompt text
            model: Model name (defaults to text_model for text, vision_model for images)
            image_path: Optional path to image file for vision tasks
            max_retries: Maximum retry attempts
            use_cache: Whether to use response cache
        
        Returns:
            Response text or None if failed
        """
        # If Gemini client not available, try Groq fallback immediately
        if not self.client:
            logger.debug("Gemini client not available, trying Groq fallback...")
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
        
        # Check cache first
        image_hash = None
        if image_path and image_path.exists():
            with open(image_path, 'rb') as f:
                image_data = f.read()
                image_hash = hashlib.md5(image_data).hexdigest()
        
        if use_cache:
            cache_key = self._get_cache_key(prompt, model, image_hash)
            if cache_key in _gemini_response_cache:
                logger.debug(f"Cache hit for prompt (model: {model})")
                return _gemini_response_cache[cache_key]
        
        for attempt in range(max_retries):
            try:
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
                
                # Extract text from response
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
                    # Cache response
                    if use_cache:
                        cache_key = self._get_cache_key(prompt, model, image_hash)
                        _gemini_response_cache[cache_key] = response_text
                    return response_text
                
                return None
                
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit errors (429 or quota exceeded)
                is_rate_limit = (
                    '429' in error_str or 
                    'quota' in error_str.lower() or 
                    'rate limit' in error_str.lower() or
                    'retry' in error_str.lower()
                )
                
                if is_rate_limit:
                    # Extract retry delay from error message if available
                    retry_delay = self._extract_retry_delay(error_str)
                    if retry_delay:
                        logger.warning(
                            f"Rate limit hit. Waiting {retry_delay}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_delay)
                    else:
                        # Default delay: exponential backoff with minimum 1 second
                        delay = min(1 * (2 ** attempt), 60)  # Max 60 seconds
                        logger.warning(
                            f"Rate limit hit. Waiting {delay}s before retry "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                else:
                    logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt == max_retries - 1:
                    logger.warning("All Gemini API retry attempts failed, trying Groq fallback...")
                    # Fallback to Groq if Gemini fails
                    if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                        logger.info("Falling back to Groq API")
                        # For image analysis, Groq uses a different approach (text-based for now)
                        if image_path:
                            logger.warning("Groq fallback for image analysis may have limited capabilities")
                            # Try text-based analysis with Groq (Groq vision is limited)
                            try:
                                groq_response = self.groq_client._call_groq(prompt, model=self.groq_client.image_model, use_cache=use_cache)
                                if groq_response:
                                    logger.info("Groq fallback succeeded for image analysis")
                                    return groq_response
                            except Exception as e:
                                logger.warning(f"Groq fallback for image analysis failed: {e}")
                        else:
                            # Text-based call with Groq
                            try:
                                groq_response = self.groq_client._call_groq(prompt, model=self.groq_client.text_model, use_cache=use_cache)
                                if groq_response:
                                    logger.info("Groq fallback succeeded for text call")
                                    return groq_response
                            except Exception as e:
                                logger.warning(f"Groq fallback for text call failed: {e}")
                    
                    logger.error("Both Gemini and Groq API calls failed")
                    return None
                
                # Small delay before retry for non-rate-limit errors
                if not is_rate_limit:
                    time.sleep(1)
        
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
        
        response = self._call_gemini(prompt)
        if not response:
            logger.warning("Theme alignment check failed (Gemini and Groq fallback), defaulting to False")
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
    
    def analyze_image(
        self,
        image_path: Path,
        event_mode: Optional[str] = None,
        event_title: Optional[str] = None,
        event_theme: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze image for event validation using Gemini Vision model.
        
        Args:
            image_path: Path to image file (Path object)
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
        
        response = self._call_gemini(prompt, image_path=image_path, use_cache=False)
        if not response:
            logger.warning("Gemini image analysis failed, trying Groq fallback...")
            # Fallback to Groq for image analysis
            if self.groq_client and hasattr(self.groq_client, 'client') and self.groq_client.client:
                try:
                    groq_results = self.groq_client.analyze_image(image_path, event_mode, event_title, event_theme)
                    if groq_results and (any(groq_results.values()) or groq_results.get("detailed_reasoning")):
                        logger.info("Groq fallback succeeded for image analysis")
                        return groq_results
                except Exception as e:
                    logger.warning(f"Groq fallback for image analysis failed: {e}")
            logger.warning("Both Gemini and Groq image analysis failed")
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
        
        response = self._call_gemini(prompt)
        if not response:
            logger.warning("PDF vision analysis failed (Gemini and Groq fallback)")
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
