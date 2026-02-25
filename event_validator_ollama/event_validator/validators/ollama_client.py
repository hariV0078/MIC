"""Ollama API client for semantic validation with vision support - Open Source LLM."""
import logging
from typing import Optional, Dict, Any
from pathlib import Path
import os
import time
import hashlib
import re
import json
from dotenv import load_dotenv

load_dotenv()

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False

logger = logging.getLogger(__name__)
_ollama_response_cache: Dict[str, str] = {}

class OllamaClient:
    def __init__(self, base_url: Optional[str] = None, text_model: Optional[str] = None, vision_model: Optional[str] = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.text_model = text_model or os.getenv("OLLAMA_TEXT_MODEL", "llama3.2:3b")
        self.vision_model = vision_model or os.getenv("OLLAMA_VISION_MODEL", "llava:latest")
        
        if not OLLAMA_AVAILABLE:
            self.client = None
        else:
            try:
                self.client = ollama.Client(host=self.base_url)
            except Exception as e:
                self.client = None
                logger.error(f"Failed to connect to Ollama at {self.base_url}: {e}")

    def _get_cache_key(self, prompt: str, model: str) -> str:
        return hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()

    def _call_ollama(self, prompt: str, model: str, max_retries: int = 2, use_cache: bool = True, options: Optional[Dict] = None) -> Optional[str]:
        if not self.client: return None
        cache_key = self._get_cache_key(prompt, model)
        if use_cache and cache_key in _ollama_response_cache: return _ollama_response_cache[cache_key]
        
        # Merge default options with user options
        final_options = {'temperature': 0.0}
        if options:
            final_options.update(options)
        
        # Import concurrency guard (delayed import to avoid circular dependencies if any)
        from event_validator.utils.concurrency import ollama_concurrency_guard
        
        for attempt in range(max_retries):
            try:
                with ollama_concurrency_guard():
                    response = self.client.generate(model=model, prompt=prompt, options=final_options)
                
                response_text = response.get('response', '').strip()
                if response_text:
                    if use_cache: _ollama_response_cache[cache_key] = response_text
                    return response_text
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Ollama attempt {attempt+1} failed: {e}")
                time.sleep(1)
        return None


    def check_iic_alignment(self, title: str, objectives: str = "", learning_outcomes: str = "", theme: str = "") -> tuple[bool, str]:
        """
        REDEFINED: Purely semantic check using LLM. Redundant Python filters removed.
        """
        # LLM Semantic Check (Flow 1)
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
        
        response = self._call_ollama(prompt, model=self.text_model, use_cache=False)
        if not response: 
            return (False, "LLM Error")
        
        passed = "YES" in response.upper().split("RESULT:")[1] if "RESULT:" in response.upper() else "YES" in response.upper()
        
        llm_reason = response.split("REASON:")[1].strip() if "REASON:" in response else "LLM Decision"
        return passed, f"LLM CHECK: {llm_reason}"
    
    def check_pdf_relevance(self, pdf_text: str, activity_name: str) -> bool:
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
        
        response = self._call_ollama(prompt, model=self.text_model, use_cache=True)
        if response:
            return "RESULT: YES" in response.upper() or ("YES" in response.upper() and "RESULT: NO" not in response.upper())
        
        # Default to True (lenient) if LLM fails
        return True

    # Legacy method wrapper
    def check_theme_alignment(self, title: str, theme: str, objectives: str = "", learning_outcomes: str = "") -> bool:
        passed, _ = self.check_iic_alignment(title, objectives, learning_outcomes, theme)
        return passed

    def extract_title_with_llm(self, first_page_text: str) -> Optional[str]:
        prompt = f"""
        Extract the official event title from the text below. Return ONLY the title.
        TEXT:
        {first_page_text[:1000]}
        """
        response = self._call_ollama(prompt, model=self.text_model, use_cache=True)
        return response.strip().strip('"') if response else None

    def validate_pdf_title(self, pdf_text: str, expected_title: str, theme: str = "") -> bool:
        """
        Validate PDF title using hybrid approach:
        1. Clean String Matching (Method 1 - Fast & Strict)
        2. LLM Semantic Check (Method 2 - Robust Fallback)
        """
        # Extract title if possible
        extracted_pdf_title = self.extract_title_with_llm(pdf_text)
        if not extracted_pdf_title:
            return False
            
        # Method 1: Clean String Matching
        cleaned_pdf_title = self._clean_title(extracted_pdf_title, theme)
        cleaned_expected_title = self._clean_title(expected_title, theme)
        
        # Check for containment or fuzzy match
        if (cleaned_pdf_title in cleaned_expected_title) or (cleaned_expected_title in cleaned_pdf_title):
            return True
            
        # Method 2: LLM Semantic Check (Fallback)
        # This mirrors the robustness of checking_iic_alignment
        prompt = f"""
        Compare these two event titles. Are they referring to the SAME event?
        
        Title 1 (From Metadata): {expected_title}
        Title 2 (Extracted from PDF): {extracted_pdf_title}
        
        Consider:
        - Minor variations (e.g. "Workshop on X" vs "Report on X")
        - Abbreviations (e.g. "IIC" vs "Institution's Innovation Council")
        - Formatting differences
        
        Respont ONLY with "YES" or "NO".
        """
        response = self._call_ollama(prompt, model=self.text_model, use_cache=True)
        if response and "YES" in response.upper():
            return True
            
        return False


    def validate_pdf_comprehensive(
        self, 
        pdf_text: str, 
        expected_title: Optional[str] = None, 
        expected_objectives: Optional[str] = None, 
        expected_learning_outcomes: Optional[str] = None,
        expected_participants: Optional[int] = None,
        pdf_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate PDF content against expected metadata using LLM.
        Single unified call that checks all PDF rules at once.
        """
        prompt = f"""You are validating a PDF report for an event submission. Analyze the PDF text and return ALL validation results in a single response.

PDF Text (first 2000 characters):
{pdf_text[:2000]}

Expected Metadata:
- Title: {expected_title or 'Not specified'}
- Objectives: {expected_objectives or 'Not specified'}
- Learning Outcomes: {expected_learning_outcomes or 'Not specified'}
- Expected Participants: {expected_participants or 'Not specified (needs 15+)'}

Task: Validate ALL of the following in ONE analysis:
1. Does the PDF title/topic match the expected title? (SIMILARITY IS ACCEPTABLE - exact match not required. Accept if titles are semantically similar, have similar meaning, or contain key words from expected title. Minor variations in wording, word order, or formatting are acceptable.)
2. Are expert details present? (Look for: expert name, designation, affiliation, speaker, facilitator, resource person, keynote speaker, presenter)
3. Do the objectives in the PDF align with the expected objectives? (semantic alignment)
4. Do the learning outcomes in the PDF align with the expected learning outcomes? (semantic alignment)
5. Does the PDF contain participant information indicating {expected_participants if expected_participants else 15}+ participants?

OUTPUT JSON ONLY:
{{
    "title_match": true/false,
    "expert_details_present": true/false,
    "objectives_match": true/false,
    "learning_match": true/false,
    "participants_valid": true/false,
    "reasoning": "short explanation"
}}
"""
        
        response = self._call_ollama(prompt, model=self.text_model, use_cache=True, options={'format': 'json'})

        
        default_result = {
            "title_match": False,
            "expert_details_present": False,
            "objectives_match": False,
            "learning_match": False,
            "participants_valid": False,
            "reasoning": "LLM Error or Empty Response"
        }
        
        if not response:
            return default_result
            
        try:
            # Extract JSON from response
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "{" in response:
                json_str = "{" + response.split("{", 1)[1].rsplit("}", 1)[0] + "}"
                
            result = json.loads(json_str)
            return {
                "title_match": bool(result.get("title_match", False)),
                "expert_details_present": bool(result.get("expert_details_present", False)),
                "objectives_match": bool(result.get("objectives_match", False)),
                "learning_match": bool(result.get("learning_match", False)),
                "participants_valid": bool(result.get("participants_valid", False)),
                "reasoning": str(result.get("reasoning", ""))
            }
        except Exception as e:
            logger.warning(f"Failed to parse PDF validation JSON: {e}")
            return default_result

    def check_pdf_consistency(self, *args, **kwargs):
        """Legacy alias"""
        return self.validate_pdf_comprehensive(*args, **kwargs)

    def analyze_image(self, image_path: str, event_mode: str = "", event_title: str = "", event_theme: str = "") -> Dict[str, Any]:
        """
        Analyze an image using the vision model.
        Returns a dictionary with validation flags.
        """
        if not self.client:
            return {}
            
        try:
            # Read image bytes
            with open(image_path, 'rb') as f:
                image_data = f.read()
                
            prompt = f"""
            Analyze this event photo for a validation system.
            Event Title: {event_title}
            Event Theme: {event_theme}
            
            CHECKLIST:
            1. Is there a banner or poster visible? (Yes/No)
            2. Is this a real event scene (people, interaction) or just a static object/screenshot? (Real/Fake)
            3. Are there more than {expected_participants if 'expected_participants' in locals() else 15} participants visible? (Yes/No)
            4. Does the scene match a '{event_mode}' event? (Yes/No)
            
            OUTPUT JSON ONLY (No markdown, no explanation outside JSON):
            {{
                "banner_detected": true,
                "real_event_scene": true,
                "has_15_plus_participants": true,
                "mode_match": true,
                "description": "short description"
            }}
            """
            
            # Import concurrency guard
            from event_validator.utils.concurrency import ollama_concurrency_guard
            
            # Ollama expects images as list of bytes or base64 strings
            with ollama_concurrency_guard():
                response = self.client.generate(
                    model=self.vision_model,
                    prompt=prompt,
                    images=[image_data],
                    options={'temperature': 0.0, 'format': 'json'}  # Try forcing JSON mode if supported
                )

            response_text = response.get('response', '').strip()
            
            # Parse JSON
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
                
                result = json.loads(json_str)
                # Normalize key names to match what image_validator.py expects
                # The prompt uses banner_detected/real_event_scene but validators read has_banner/is_real_event
                normalized = {}
                normalized["has_banner"] = result.get("has_banner", result.get("banner_detected", False))
                normalized["is_real_event"] = result.get("is_real_event", result.get("real_event_scene", False))
                normalized["has_15_plus_participants"] = result.get("has_15_plus_participants", False)
                normalized["mode_match"] = result.get("mode_match", False)
                normalized["description"] = result.get("description", "")
                return normalized
            except Exception:
                logger.warning(f"Failed to parse image analysis JSON: {response_text[:100]}...")
                return {}
                
        except Exception as e:
            logger.error(f"Error analyzing image {image_path}: {e}")
            return {}

    def extract_text_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from an image using the vision model (OCR-like).
        Now supporting EasyOCR for robust and fast extraction.
        
        Returns:
            Dict with keys: extracted_text, has_event_details, event_details_found
        """
        result = {
            "extracted_text": "",
            "has_event_details": False,
            "event_details_found": []
        }
        
        if not self.client:
            return result
        
        try:
             # OPTIMIZATION: Use EasyOCR (Method 1) of Vision Model
            # This is faster (1s vs 45s) and more accurate for "GPS Map Camera" overlays
            try:
                from event_validator.utils.ocr import extract_visual_geotag
                has_ocr_geotag, ocr_text = extract_visual_geotag(str(image_path))
                
                if ocr_text and len(ocr_text.strip()) > 5:
                    extracted_text = ocr_text
                    logger.info(f"Using EasyOCR text for {Path(image_path).name} (Length: {len(extracted_text)})")
                    if has_ocr_geotag:
                        logger.info("EasyOCR detected visual geotag keywords.")
                else:
                    # Fallback to Vision Model
                    # Only if OCR text is suspiciously short or empty
                    extracted_text = "" 
            except Exception as e:
                logger.warning(f"EasyOCR logic failed: {e}")
                extracted_text = ""

            # Standard Vision Model Fallback (Only if EasyOCR yielded no useful text)
            if not extracted_text:
                try:
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                    
                    prompt = """Read ALL text visible in this image. Extract every word, number, date, and line of text you can see.
                    
                    OUTPUT: Return ONLY the extracted text, nothing else. If no text is visible, return "NO TEXT FOUND"."""
                    
                    from event_validator.utils.concurrency import ollama_concurrency_guard
                    with ollama_concurrency_guard():
                        response = self.client.generate(
                            model=self.vision_model,
                            prompt=prompt,
                            images=[image_data],
                            options={'temperature': 0.0}
                        )
                    extracted_text = response.get('response', '').strip()
                except Exception as e:
                    logger.error(f"Vision model fallback failed: {e}")

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