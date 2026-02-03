"""Ollama API client for semantic validation with vision support - Open Source LLM."""
import logging
from typing import Optional, Dict, Any
import os
import time
import re
import hashlib
import base64
from pathlib import Path
from dotenv import load_dotenv
from event_validator.utils.rate_limiter import get_rate_limiter
from event_validator.utils.circuit_breaker import get_ollama_circuit_breaker
from event_validator.utils.concurrency import ollama_concurrency_guard

# Load environment variables from .env file
load_dotenv()

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global cache for Ollama API responses (keyed by content hash)
_ollama_response_cache: Dict[str, str] = {}
_ollama_parsed_cache: Dict[str, Dict[str, Any]] = {}


class OllamaClient:
    """Client for interacting with Ollama models - optimized for local deployment."""
    
    def __init__(self, base_url: Optional[str] = None, text_model: Optional[str] = None, vision_model: Optional[str] = None):
        """
        Initialize Ollama client with optimal models.
        
        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
            text_model: Text model name (default: llama3.2:3b or llama3.1:8b)
            vision_model: Vision model name (default: llava:latest)
        """
        # Default to localhost for Ubuntu deployment
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        # Use efficient models - adjust based on available GPU/RAM
        # llama3.2:1b is significantly faster on CPU than 3b
        self.text_model = text_model or os.getenv("OLLAMA_TEXT_MODEL", "llama3.2:1b")
        # llava:latest supports vision tasks
        self.vision_model = vision_model or os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
        
        # Initialize Ollama client
        if not OLLAMA_AVAILABLE:
            logger.error("ollama package not installed. Install with: pip install ollama")
            self.client = None
        else:
            try:
                # Test connection to Ollama server
                self.client = ollama.Client(host=self.base_url)
                # Test if models are available
                try:
                    # Test connection and list models
                    models_response = self.client.list()
                    # Ollama list() returns {'models': [{'name': '...', ...}, ...]}
                    if isinstance(models_response, dict) and 'models' in models_response:
                        available_models = [m.get('name', '') for m in models_response['models']]
                    elif isinstance(models_response, list):
                        available_models = [m.get('name', '') if isinstance(m, dict) else str(m) for m in models_response]
                    else:
                        available_models = []
                    
                    logger.info(f"Ollama client initialized. Base URL: {self.base_url}")
                    logger.info(f"Text model: {self.text_model}, Vision model: {self.vision_model}")
                    if available_models:
                        logger.info(f"Available models: {', '.join(available_models[:5])}...")
                    
                    # Check if required models are available, if not, pull them
                    if self.text_model not in available_models:
                        logger.warning(f"Text model {self.text_model} not found. Attempting to pull...")
                        try:
                            # Pull model (this may take a while)
                            for chunk in self.client.pull(self.text_model, stream=True):
                                if chunk.get('status') == 'success':
                                    logger.info(f"Successfully pulled {self.text_model}")
                                    break
                        except Exception as e:
                            logger.error(f"Failed to pull {self.text_model}: {e}. You may need to pull it manually: ollama pull {self.text_model}")
                    
                    if self.vision_model not in available_models:
                        logger.warning(f"Vision model {self.vision_model} not found. Attempting to pull...")
                        try:
                            # Pull model (this may take a while)
                            for chunk in self.client.pull(self.vision_model, stream=True):
                                if chunk.get('status') == 'success':
                                    logger.info(f"Successfully pulled {self.vision_model}")
                                    break
                        except Exception as e:
                            logger.error(f"Failed to pull {self.vision_model}: {e}. You may need to pull it manually: ollama pull {self.vision_model}")
                            
                except Exception as e:
                    logger.warning(f"Could not list Ollama models: {e}. Continuing anyway...")
                    # Client is already initialized, continue
                    
            except Exception as e:
                logger.error(f"Failed to initialize Ollama client: {e}")
                logger.error(f"Make sure Ollama is running: ollama serve")
                self.client = None
    
    def _get_cache_key(self, prompt: str, model: Optional[str] = None, image_hash: Optional[str] = None, pdf_hash: Optional[str] = None) -> str:
        """Generate cache key for prompt, model, and optionally image/pdf hash."""
        content = f"{model or self.text_model}:{prompt}"
        if image_hash:
            content += f":img:{image_hash}"
        if pdf_hash:
            content += f":pdf:{pdf_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _call_ollama(
        self,
        prompt: str,
        model: Optional[str] = None,
        image_path: Optional[Path] = None,
        max_retries: int = 3,
        use_cache: bool = True
    ) -> Optional[str]:
        """
        Call Ollama API with retry logic, rate limit handling, and caching.
        
        Args:
            prompt: Prompt text
            model: Model name (defaults to text_model for text, vision_model for images)
            image_path: Optional path to image file for vision tasks
            max_retries: Maximum retry attempts
            use_cache: Whether to use response cache
        
        Returns:
            Response text or None if failed
        """
        if not self.client:
            logger.error("Ollama client not available")
            return None
        
        # Determine model based on whether image is provided
        if image_path:
            model = model or self.vision_model
        else:
            model = model or self.text_model
        
        # Check cache first
        image_hash = None
        if image_path and image_path.exists():
            try:
                from event_validator.utils.hashing import compute_sha256
                image_hash = compute_sha256(image_path)
            except Exception as e:
                logger.debug(f"Could not compute image hash for caching: {e}")
        
        if use_cache and image_hash:
            cache_key = self._get_cache_key(prompt, model, image_hash=image_hash[:16])
            if cache_key in _ollama_response_cache:
                logger.debug(f"Cache hit for image analysis (model: {model})")
                return _ollama_response_cache[cache_key]
        elif use_cache and not image_path:
            cache_key = self._get_cache_key(prompt, model)
            if cache_key in _ollama_response_cache:
                logger.debug(f"Cache hit for text prompt (model: {model})")
                return _ollama_response_cache[cache_key]
        
        # Use rate limiter (Ollama can handle higher rates locally, but still use limiter)
        rate_limiter = get_rate_limiter()
        estimated_tokens = rate_limiter.estimate_tokens(prompt, has_image=(image_path is not None))
        delay = rate_limiter.acquire(wait=True, estimated_tokens=estimated_tokens)
        if delay > 0:
            logger.debug(f"Rate limiter applied {delay:.2f}s delay")
        
        # Use concurrency guard
        with ollama_concurrency_guard():
            # Retry logic
            last_error = None
            for attempt in range(max_retries):
                try:
                    if image_path and image_path.exists():
                        # Vision task - Ollama accepts image path directly or base64
                        # Read image and convert to base64
                        with open(image_path, 'rb') as img_file:
                            image_data = img_file.read()
                            image_base64 = base64.b64encode(image_data).decode('utf-8')
                        
                        # Ollama vision API format - use generate with images parameter
                        response = self.client.generate(
                            model=model,
                            prompt=prompt,
                            images=[image_base64],
                            options={
                                'temperature': 0.1,  # Lower temperature for more consistent validation
                                'top_p': 0.9,
                                'num_predict': 120,  # OPTIMIZATION: Cap vision output tokens
                            }
                        )
                    else:
                        # Text-only task
                        response = self.client.generate(
                            model=model,
                            prompt=prompt,
                            options={
                                'temperature': 0.1,
                                'top_p': 0.9,
                                'num_predict': 80,   # OPTIMIZATION: Cap text output tokens
                            }
                        )
                    
                    # Extract response text from Ollama response
                    if isinstance(response, dict):
                        # Chat API returns {'message': {'content': '...'}}
                        if 'message' in response:
                            response_text = response['message'].get('content', '')
                        # Generate API returns {'response': '...'}
                        elif 'response' in response:
                            response_text = response['response']
                        else:
                            response_text = str(response)
                    else:
                        response_text = str(response)
                    
                    if response_text:
                        # Cache the response
                        if use_cache:
                            cache_key = self._get_cache_key(prompt, model, image_hash=image_hash[:16] if image_hash else None)
                            _ollama_response_cache[cache_key] = response_text
                            logger.debug(f"Cached response with key: {cache_key[:16]}...")
                        
                        return response_text
                    else:
                        logger.warning(f"Empty response from Ollama (attempt {attempt + 1}/{max_retries})")
                        
                except Exception as e:
                    last_error = e
                    logger.warning(f"Ollama API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1 * (attempt + 1))  # Exponential backoff
                    else:
                        logger.error(f"All Ollama API retries failed: {e}")
            
            return None
    
    def check_theme_alignment(
        self,
        title: str,
        objectives: str,
        learning_outcomes: str,
        theme: str,
        prefer_groq: bool = False  # Kept for interface compatibility
    ) -> bool:
        """
        Check if title, objectives, and learning outcomes align with theme.
        Returns True if aligned, False otherwise.
        """
        prompt = f"""You are a validation system. Determine if the following event details are relevant to the specified theme.

Theme: {theme}

Event Title: {title}
Objectives: {objectives}
Learning Outcomes: {learning_outcomes}

Task: Check if there is RELEVANCY between the event details and the theme. Be LENIENT but not too lenient - accept if there is meaningful relevance or connection to the theme, even if not a perfect match. Reject only if there is clearly no relevance or connection.

Guidelines:
- Accept if the event is relevant to the theme, even with some variation
- Accept if key concepts from the theme appear in the event details
- Accept if the event addresses topics related to the theme
- Reject only if there is clearly no connection or relevance

Respond with ONLY one word: "YES" if relevant, "NO" if not relevant."""
        
        response = self._call_ollama(prompt, use_cache=True)
        if response:
            return "YES" in response.upper()
        
        logger.warning("Theme alignment check failed")
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
{pdf_text[:2500]}

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
        
        response = self._call_ollama(prompt)
        if not response:
            logger.warning("PDF consistency check failed")
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
                f"pdf_validation:{expected_title}:{expected_objectives}:{expected_learning_outcomes}:{expected_participants}",
                model=self.text_model,
                pdf_hash=pdf_hash
            )
            # Check cache first
            if cache_key in _ollama_parsed_cache:
                logger.debug("PDF validation cache hit (parsed results)")
                return _ollama_parsed_cache[cache_key]
            elif cache_key in _ollama_response_cache:
                logger.debug("PDF validation cache hit (raw response)")
                cached_response = _ollama_response_cache[cache_key]
                parsed_results = self._parse_pdf_validation_response(cached_response)
                _ollama_parsed_cache[cache_key] = parsed_results
                return parsed_results
        
        results = {
            "title_match": False,
            "expert_details_present": False,
            "learning_outcomes_align": False,
            "objectives_match": False,
            "participants_valid": False,
            "reasoning": ""
        }
        
        prompt = f"""You are a validation system. Analyze the following PDF text and check all validation criteria.

PDF Text:
{pdf_text[:2500]}

Expected Title: {expected_title or 'Not provided'}
Expected Objectives: {expected_objectives or 'Not provided'}
Expected Learning Outcomes: {expected_learning_outcomes or 'Not provided'}
Expected Participants: {expected_participants or 'Not provided'}

Task: Check ALL of the following:
1. Does the PDF title match the expected title? (SIMILARITY IS ACCEPTABLE - exact match not required)
2. Are expert details present in the PDF? (Look for expert names, speaker information, facilitator details)
3. Do the learning outcomes in the PDF align with expected learning outcomes?
4. Do the objectives in the PDF match the expected objectives?
5. Does the PDF contain participant information indicating 15+ participants?

Respond in this EXACT format (one line per check):
TITLE_MATCH: YES or NO
EXPERT_DETAILS: YES or NO
LEARNING_OUTCOMES_ALIGN: YES or NO
OBJECTIVES_MATCH: YES or NO
PARTICIPANTS_VALID: YES or NO
REASONING: <brief explanation of your findings>"""
        
        response = self._call_ollama(prompt, use_cache=True)
        if not response:
            logger.warning("Comprehensive PDF validation failed")
            return results
        
        # Parse and cache the response
        parsed_results = self._parse_pdf_validation_response(response)
        if cache_key:
            _ollama_response_cache[cache_key] = response
            _ollama_parsed_cache[cache_key] = parsed_results
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
        Analyze image for event validation using Ollama Vision model.
        
        Args:
            image_path: Path to image file (Path object)
            event_mode: Event mode (online/offline)
            event_title: Event title for banner text validation
            event_theme: Event theme for context
        
        Returns:
            Dict with keys: has_banner, is_real_event, mode_matches, has_15_plus_participants,
            banner_text_matches, participant_count_estimate, detailed_reasoning
        """
        results = {
            "has_banner": False,
            "is_real_event": False,
            "mode_matches": False,
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
        
        if not self.client:
            logger.error("Ollama client not available for image analysis")
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
HAS_15_PLUS_PARTICIPANTS: YES or NO
REASONING: <brief explanation>"""
        
        response = self._call_ollama(prompt, image_path=image_path, use_cache=False)
        if not response:
            logger.warning("Ollama image analysis failed")
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
            elif 'HAS_15_PLUS_PARTICIPANTS:' in line:
                results["has_15_plus_participants"] = "YES" in line.upper()
            elif 'REASONING:' in line:
                results["detailed_reasoning"] = line.split(':', 1)[1].strip() if ':' in line else ""
        
        return results
