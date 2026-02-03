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
                                'num_predict': 512,   # INCREASED: Allow for CoT reasoning
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
        prefer_groq: bool = False
    ) -> tuple[bool, str]:
        """
        Check if title/objectives align with theme using RULE-BASED keyword matching.
        NO AI REASONING - Pure Python logic.
        Returns Tuple[aligned: bool, reasoning: str]
        """
        from event_validator.utils.rule_based_validator import check_theme_alignment_rules
        
        # Use rule-based validation (no AI inference)
        aligned, reasoning = check_theme_alignment_rules(title, objectives, learning_outcomes, theme)
        
        logger.info(f"Rule-based theme validation: {aligned} - {reasoning}")
        return aligned, reasoning
    
    def check_pdf_consistency(
        self,
        pdf_text: str,
        expected_title: Optional[str],
        expected_objectives: Optional[str],
        expected_learning_outcomes: Optional[str],
        expected_participants: Optional[int]
    ) -> Dict[str, Any]:
        """
        Check PDF text for consistency with expected values.
        Returns dict with keys: title_match, objectives_match, learning_match, participants_valid, reasoning
        """
        results = {
            "title_match": False,
            "objectives_match": False,
            "learning_match": False,
            "participants_valid": False,
            "reasoning": ""
        }
        
        prompt = f"""You are an EXTRACTIVE validation system. Search for EVIDENCE in the PDF text.

EXPECTED DATA:
- Title: {expected_title or 'N/A'}
- Objectives: {expected_objectives or 'N/A'}
- Outcomes: {expected_learning_outcomes or 'N/A'}
- Min Participants: 15

PDF TEXT (EXTRACT):
---
{pdf_text[:4000]}
---

Return ONLY these exact lines:
TITLE_MATCH: YES/NO
OBJECTIVES_MATCH: YES/NO
LEARNING_MATCH: YES/NO
PARTICIPANTS_VALID: YES/NO
REASONING: <Quote the exact sentence used as evidence>"""
        
        response = self._call_ollama(prompt)
        if not response:
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
            elif 'REASONING:' in line:
                results["reasoning"] = line.split(':', 1)[1].strip() if ':' in line else ""
        
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
        
        # Prepare extractive search with STRICT step-by-step instructions
        expected_title_clean = re.sub(r'[^a-zA-Z0-9\s]', '', (expected_title or "").lower())
        title_keywords = " ".join([w for w in expected_title_clean.split() if len(w) > 3])[:100]

        prompt = f"""ROLE: Data Extraction Bot. Be literal.

TASK: Extract specific information from PDF text.

EXPECTED VALUES:
- Title Keywords: {title_keywords}
- Objectives: {(expected_objectives or 'N/A')[:150]}
- Min Participants: 15

PDF TEXT:
---
{pdf_text[:6000]}
---

STEP-BY-STEP INSTRUCTIONS:
1. TITLE: Find the title in PDF. Does it contain words from "{title_keywords}"?
2. EXPERT: Find names of people (speakers, faculty, trainers)
3. OBJECTIVES: Find sentences about goals/outcomes. Do they match "{(expected_objectives or 'N/A')[:80]}"?
4. PARTICIPANTS: Find numbers near 'student', 'faculty', 'participant'. List all numbers.

OUTPUT (exact format):
TITLE_MATCH: YES/NO
EXPERT_DETAILS: YES/NO
LEARNING_OUTCOMES_ALIGN: YES/NO
OBJECTIVES_MATCH: YES/NO
PARTICIPANTS_VALID: YES/NO
EVIDENCE: <Quote 1-2 sentences you found>"""
        
        response = self._call_ollama(prompt, use_cache=True)
        if not response:
            logger.warning("Comprehensive PDF validation failed")
            return results
        
        # Parse response - look for EVIDENCE or REASONING
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
            elif 'EVIDENCE:' in line or 'REASONING:' in line:
                results["reasoning"] = line.split(':', 1)[1].strip() if ':' in line else line
        
        # Cache if needed
        if cache_key:
            _ollama_response_cache[cache_key] = response
            _ollama_parsed_cache[cache_key] = results
            logger.debug(f"Cached PDF validation results with key: {cache_key[:16]}...")
        
        return results
    
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
        
        # Build extractive prompt for vision analysis
        prompt = f"""You are an EXTRACTIVE vision bot. 
- Expected Event Title: {event_title or 'N/A'}
- Expected Mode: {event_mode or 'N/A'}

DIRECTIONS:
1. DESCRIPTIVE SCAN: List the primary objects (e.g., "people", "laptop", "stage", "poster").
2. TEXT SCAN: Read any text from banners/posters. Does it relate to the Title?
3. PEOPLE COUNT: Count the humans visible.

DECISION RULES:
- HAS_BANNER: YES if any poster/banner/flyer is visible.
- BANNER_TEXT_MATCHES: YES if the visible banner text contains words from "{event_title}".
- IS_REAL_EVENT: YES if you see people or a venue setup.
- MODE_MATCHES: YES if "{event_mode}" is "online" and you see screens, OR if "{event_mode}" is "offline" and you see a physical venue.
- HAS_15_PLUS_PARTICIPANTS: YES if human count >= 15.

FORMAT:
HAS_BANNER: YES or NO
BANNER_TEXT_MATCHES: YES or NO
IS_REAL_EVENT: YES or NO
MODE_MATCHES: YES or NO
PARTICIPANT_COUNT: <number>
HAS_15_PLUS_PARTICIPANTS: YES or NO
REASONING: <Detailed evidence seen in image>"""
        
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
