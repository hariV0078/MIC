# Event Validation System - Detailed Process Documentation

This document provides a comprehensive explanation of how the Event Validation System processes submissions, including the complete calling flow, validation steps, API interactions, and scoring mechanism.

## Table of Contents

1. [System Overview](#system-overview)
2. [Entry Point and Initialization](#entry-point-and-initialization)
3. [CSV Processing Flow](#csv-processing-flow)
4. [Single Submission Processing](#single-submission-processing)
5. [Validation Steps in Detail](#validation-steps-in-detail)
6. [API Calls and Rate Limiting](#api-calls-and-rate-limiting)
7. [Scoring and Status Determination](#scoring-and-status-determination)
8. [Output Generation](#output-generation)

---

## System Overview

The Event Validation System is a rule-based validation engine that uses:
- **Hardcoded validation rules** with binary scoring (pass/fail)
- **Google Gemini AI** for semantic analysis (text and vision models)
- **Groq Cloud** as a fallback when Gemini fails
- **SHA256 and pHash** for duplicate detection
- **Sequential processing** for CSV files (CLI mode)

### Key Components

```
main.py (CLI Entry Point)
    ↓
process_csv() (Orchestration)
    ↓
process_submission() (Single Submission Handler)
    ↓
    ├── Column Mapping
    ├── File Extraction (PDF + Images)
    ├── Theme Validation
    ├── PDF Validation
    ├── Image Validation
    ├── Duplicate Validation
    └── Score Aggregation
```

---

## Entry Point and Initialization

### 1. CLI Entry Point (`main.py`)

**Interactive Mode (Default):**
```bash
python main.py
```

**Process:**
1. Prompts user for input CSV file path
2. Validates file exists
3. Auto-generates output path in `./outputs/` directory
4. Loads configuration from environment variables (`.env` file)
5. Calls `process_csv()` to start processing

**Non-Interactive Mode:**
```bash
python main.py --non-interactive input.csv --output-csv output.csv
```

**Configuration Loading:**
- Reads from `.env` file or environment variables
- Key settings:
  - `GEMINI_API_KEY`: Primary AI service
  - `GROQ_API_KEY`: Fallback AI service
  - `ACCEPTANCE_THRESHOLD`: Minimum score for acceptance (default: 60)
  - `PHASH_THRESHOLD`: Duplicate detection sensitivity (default: 5)
  - `BASE_IMAGE_PATH`: Base directory for duplicate scanning

### 2. Gemini Client Initialization

**Location:** `event_validator/validators/gemini_client.py`

**Initialization Process:**
1. Creates Gemini client with:
   - Text model: `gemini-2.0-flash-exp` (for text analysis)
   - Vision model: `gemini-2.5-pro` (for image analysis)
2. Initializes Groq fallback client:
   - Text model: `llama-3.1-8b-instant`
   - Image model: `meta-llama/llama-4-scout-17b-16e-instruct`
3. Sets up rate limiter (TokenBucketRateLimiter):
   - Default: 13 RPM (90% of 15 RPM limit)
   - Automatically calculates delays between API calls
4. Registers rate limit callback for sequential mode switching

---

## CSV Processing Flow

### Function: `process_csv()`

**Location:** `event_validator/orchestration/runner.py:327`

**Step-by-Step Process:**

#### Step 1: Initialize Clients
```python
gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_api_key)
```
- Creates Gemini client with Groq fallback
- Validates API keys are set

#### Step 2: Read Input CSV
```python
with open(input_csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
```
- Reads CSV file with UTF-8 encoding
- Converts each row to dictionary
- Preserves original column names

#### Step 3: Reset Batch Hash Tracker
```python
reset_batch_hash_tracker()
```
- Clears duplicate detection cache
- Ensures each batch starts fresh

#### Step 4: Process Each Row Sequentially
```python
for i, row in enumerate(rows, 1):
    submission = process_submission(row, config, gemini_client)
    # Add results to output
```
- Processes one submission at a time
- Handles errors gracefully (continues on failure)
- Logs progress for each submission

#### Step 5: Write Output CSV
```python
with open(output_csv_path, 'w', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=output_fieldnames)
    writer.writeheader()
    writer.writerows(enriched_rows)
```
- Adds new columns: `Overall Score`, `Status`, `Requirements Not Met`
- Uses UTF-8-sig encoding for Excel compatibility
- Preserves all original columns

---

## Single Submission Processing

### Function: `process_submission()`

**Location:** `event_validator/orchestration/runner.py:27`

**Complete Flow:**

```
process_submission()
    │
    ├─► Step 1: Column Mapping
    │   └─► map_row_to_standard_format()
    │       ├─► Maps CSV columns to standard format
    │       ├─► Extracts: Title, Objectives, Learning Outcomes, Theme, Level, Duration, etc.
    │       └─► Determines Level from Duration (if not provided)
    │
    ├─► Step 2: File Extraction
    │   ├─► PDF Extraction (MANDATORY)
    │   │   ├─► Resolve path/URL using blob_path_resolver
    │   │   ├─► Download from Azure Blob Storage (if URL)
    │   │   ├─► Extract text using pdfplumber or PyPDF2
    │   │   └─► Store in submission.pdf_data
    │   │
    │   └─► Image Extraction (AT LEAST 1 MANDATORY)
    │       ├─► Parse comma/semicolon-separated paths
    │       ├─► Download images from Azure Blob Storage (if URLs)
    │       ├─► Extract metadata (SHA256, pHash, geotag)
    │       └─► Store in submission.images[]
    │
    ├─► Step 3: Theme Validation (33 points)
    │   ├─► validate_theme_alignment() - 10 points
    │   ├─► validate_level_duration_match() - 11 points
    │   └─► validate_participant_count() - 12 points
    │
    ├─► Step 4: PDF Validation (25 points)
    │   ├─► validate_pdf_title_match() - 5 points
    │   ├─► validate_expert_details() - 7 points
    │   ├─► validate_learning_outcomes() - 5 points
    │   ├─► validate_objectives_match() - 5 points
    │   └─► validate_participant_info() - 3 points
    │
    ├─► Step 5: Image Validation (14 points)
    │   ├─► OPTIMIZED: Single analyze_image() call
    │   ├─► validate_banner_poster_visible() - 3 points
    │   ├─► validate_real_activity_scene() - 4 points
    │   ├─► validate_event_mode_matches() - 3 points
    │   └─► validate_20_plus_participants_visible() - 4 points
    │
    ├─► Step 6: Duplicate Validation (15 points)
    │   └─► validate_duplicate_detection() - 15 points
    │       ├─► Batch-level duplicate check (within CSV)
    │       └─► Directory-level duplicate check (event_driven folder)
    │
    ├─► Step 7: Score Aggregation
    │   ├─► Sum all validation points
    │   ├─► Calculate overall_score
    │   └─► Generate requirements_not_met message
    │
    └─► Step 8: Status Determination
        ├─► Check mandatory files (PDF + at least 1 image)
        ├─► Compare score to acceptance_threshold
        └─► Set status: Accepted / Rejected / Reopen / Error
```

---

## Validation Steps in Detail

### 1. Column Mapping

**Function:** `map_row_to_standard_format()`

**Location:** `event_validator/utils/column_mapper.py:44`

**Purpose:** Converts CSV column names to standardized format

**Mapping Table:**
| CSV Column | Standard Field | Notes |
|------------|----------------|-------|
| `activity_name` | `Title` | Event title |
| `Objective` | `Objectives` | Event objectives |
| `benefit_learning` | `Learning Outcomes` | Learning outcomes |
| `event_theme` | `Theme` | Event theme |
| `event_type` | `Event Type` | Type of event |
| `activity_duration` | `Duration` | Converted to hours (e.g., "3h") |
| `student_participants + faculty_participants` | `Participants` | Sum of both |
| `from_date` | `Event Date` | Event date |
| `financial_year` | `Year Type` | Financial or Academic |
| `session_type` | `Event Mode` | Online or Offline |
| `report` | `PDF Path` | Resolved to full URL |
| `photo1, photo2` | `Image Paths` | Comma-separated, resolved URLs |

**Level Determination:**
- If `Level` not provided, calculates from `Duration`:
  - 2-4 hours → Level 1
  - 5-8 hours → Level 2
  - 9-18 hours → Level 3
  - >18 hours → Level 4

---

### 2. File Extraction

#### PDF Extraction

**Function:** `extract_pdf_text()`

**Location:** `event_validator/extractors/pdf_extractor.py`

**Process:**
1. **Path Resolution:**
   - If relative path: Resolve using `blob_path_resolver`
   - If URL: Use directly
   - Handles `event_driven` and `academic_year` for path construction

2. **Download (if URL):**
   - Downloads from Azure Blob Storage
   - Saves to `./downloaded_files/` directory
   - Handles 404 errors gracefully

3. **Text Extraction:**
   - **Primary:** Uses `pdfplumber` library
   - **Fallback:** Uses `PyPDF2` if pdfplumber fails
   - Extracts all text content
   - Stores in `submission.pdf_data`

**Error Handling:**
- Missing PDF → `pdf_missing = True`
- Invalid PDF → `pdf_data = None`
- Both trigger "Reopen" status

#### Image Extraction

**Function:** `extract_images_from_paths()`

**Location:** `event_validator/extractors/image_extractor.py`

**Process:**
1. **Path Parsing:**
   - Supports comma or semicolon-separated paths
   - Filters out invalid paths (`0`, `null`, `none`, `n/a`)

2. **Download (if URLs):**
   - Downloads each image from Azure Blob Storage
   - Saves to `./downloaded_files/` directory
   - Handles 404 errors gracefully

3. **Metadata Extraction:**
   - **SHA256 Hash:** Exact duplicate detection
   - **pHash (Perceptual Hash):** Similar image detection
   - **Geotag:** EXIF location data (currently disabled)
   - **File Path:** Original or downloaded path

4. **Image Data Structure:**
   ```python
   ImageData(
       path: Path,
       sha256: str,
       phash: Optional[str],
       has_geotag: bool
   )
   ```

**Error Handling:**
- Missing images → `images_missing = True`
- Invalid images → Skipped with warning
- At least 1 image required → Triggers "Reopen" status

---

### 3. Theme Validation

**Function:** `validate_theme()`

**Location:** `event_validator/validators/theme_validator.py`

**Total Points:** 33 (Year alignment disabled)

#### 3.1 Theme Alignment Check (10 points)

**Function:** `validate_theme_alignment()`

**Process:**
1. **API Call:** `gemini_client.analyze_text()`
   - Model: `gemini-2.0-flash-exp`
   - Prompt: Checks if Title, Objectives, and Learning Outcomes align with declared Theme
   - Response: YES/NO with reasoning

2. **Scoring:**
   - **PASS:** 10 points (all content aligns with theme)
   - **FAIL:** 0 points (content doesn't align)

**Example Prompt:**
```
Analyze if the following content aligns with the theme "Innovation":
- Title: "Workshop on AI Ethics"
- Objectives: "To understand ethical implications of AI"
- Learning Outcomes: "Participants will learn about AI ethics frameworks"

Respond: THEME_ALIGNMENT: YES or NO
```

#### 3.2 Level-Duration Match (11 points)

**Function:** `validate_level_duration_match()`

**Process:**
1. **Extract Level and Duration:**
   - Level: From CSV or calculated from duration
   - Duration: Converted to hours (float)

2. **Validation Rules:**
   - Level 1: 2-4 hours
   - Level 2: 5-8 hours
   - Level 3: 9-18 hours
   - Level 4: >18 hours

3. **Scoring:**
   - **PASS:** 11 points (level matches duration range)
   - **FAIL:** 0 points (mismatch)

**Note:** Year alignment validation is **DISABLED** per user request.

#### 3.3 Participant Count Check (12 points)

**Function:** `validate_participant_count()`

**Process:**
1. **Extract Participants:**
   - Sum of `student_participants` + `faculty_participants`
   - Or from `Participants` field directly

2. **Validation:**
   - **PASS:** 12 points (if participants > 20)
   - **FAIL:** 0 points (if participants ≤ 20)

**No API call required** - Simple numeric comparison.

---

### 4. PDF Validation

**Function:** `validate_pdf()`

**Location:** `event_validator/validators/pdf_validator.py`

**Total Points:** 25

**Prerequisite:** PDF text must be extracted successfully

#### 4.1 PDF Title Match (5 points)

**Function:** `validate_pdf_title_match()`

**Process:**
1. **API Call:** `gemini_client.analyze_pdf_with_vision()`
   - Model: `gemini-2.0-flash-exp`
   - Input: Extracted PDF text + Expected title
   - Prompt: Check if PDF title matches expected title (fuzzy match allowed)

2. **Scoring:**
   - **PASS:** 5 points (title matches)
   - **FAIL:** 0 points (title doesn't match)

#### 4.2 Expert Details Present (7 points)

**Function:** `validate_expert_details()`

**Process:**
1. **API Call:** `gemini_client.analyze_pdf_with_vision()`
   - Model: `gemini-2.0-flash-exp`
   - Prompt: Check if PDF contains expert/resource person details (name, designation, affiliation)

2. **Scoring:**
   - **PASS:** 7 points (expert details found)
   - **FAIL:** 0 points (expert details not found)

#### 4.3 Learning Outcomes Alignment (5 points)

**Function:** `validate_learning_outcomes_alignment()`

**Process:**
1. **API Call:** `gemini_client.analyze_pdf_with_vision()`
   - Model: `gemini-2.0-flash-exp`
   - Input: PDF text + Expected learning outcomes
   - Prompt: Check if PDF learning outcomes align with expected outcomes

2. **Scoring:**
   - **PASS:** 5 points (outcomes align)
   - **FAIL:** 0 points (outcomes don't align)

#### 4.4 Objectives Match (5 points)

**Function:** `validate_objectives_match()`

**Process:**
1. **API Call:** `gemini_client.analyze_pdf_with_vision()`
   - Model: `gemini-2.0-flash-exp`
   - Input: PDF text + Expected objectives
   - Prompt: Check if PDF objectives match expected objectives

2. **Scoring:**
   - **PASS:** 5 points (objectives match)
   - **FAIL:** 0 points (objectives don't match)

#### 4.5 Participant Info Match (3 points)

**Function:** `validate_participant_info_match()`

**Process:**
1. **API Call:** `gemini_client.analyze_pdf_with_vision()`
   - Model: `gemini-2.0-flash-exp`
   - Input: PDF text + Expected participant count
   - Prompt: Check if PDF contains participant information indicating 20+ participants

2. **Scoring:**
   - **PASS:** 3 points (20+ participants confirmed in PDF)
   - **FAIL:** 0 points (participant info missing or <20)

**Note:** If PDF text extraction fails, all PDF validations return 0 points with "PDF text not extracted" message.

---

### 5. Image Validation

**Function:** `validate_images()`

**Location:** `event_validator/validators/image_validator.py`

**Total Points:** 14 (Geotag validation disabled)

**Optimization:** Single API call per image (reused for all 4 checks)

#### 5.1 Image Analysis (Single API Call)

**Function:** `gemini_client.analyze_image()`

**Location:** `event_validator/validators/gemini_client.py:397`

**Process:**
1. **API Call:** Gemini Vision API
   - Model: `gemini-2.5-pro`
   - Input: Image file (base64 encoded) + Event context
   - Prompt: Comprehensive analysis covering all 4 validation checks

2. **Response Format:**
   ```
   HAS_BANNER: YES or NO
   BANNER_TEXT_MATCHES: YES or NO
   IS_REAL_EVENT: YES or NO
   MODE_MATCHES: YES or NO
   PARTICIPANT_COUNT: <number>
   HAS_20_PLUS_PARTICIPANTS: YES or NO
   REASONING: <brief explanation>
   ```

3. **Analysis Result Dictionary:**
   ```python
   {
       "has_banner": bool,
       "is_real_event": bool,
       "mode_matches": bool,
       "has_20_plus_participants": bool,
       "banner_text_matches": bool,
       "participant_count_estimate": int,
       "detailed_reasoning": str
   }
   ```

**Key Optimization:** This single analysis result is reused for all 4 validation functions, reducing API calls from 4 to 1 per image.

#### 5.2 Banner/Poster Visible (3 points)

**Function:** `validate_banner_poster_visible()`

**Process:**
1. **Extract from Analysis:**
   - Uses `analysis["has_banner"]` from single API call
   - No additional API call needed

2. **Scoring:**
   - **PASS:** 3 points (banner/poster visible)
   - **FAIL:** 0 points (banner/poster not visible)

#### 5.3 Real Activity Scene (4 points)

**Function:** `validate_real_activity_scene()`

**Process:**
1. **Extract from Analysis:**
   - Uses `analysis["is_real_event"]` from single API call
   - No additional API call needed

2. **Scoring:**
   - **PASS:** 4 points (real event activity detected)
   - **FAIL:** 0 points (not a real event, possibly stock photo or staged)

#### 5.4 Event Mode Match (3 points)

**Function:** `validate_event_mode_matches()`

**Process:**
1. **Extract from Analysis:**
   - Uses `analysis["mode_matches"]` from single API call
   - Compares image content with declared mode (Online/Offline)

2. **Scoring:**
   - **PASS:** 3 points (mode matches)
   - **FAIL:** 0 points (mode mismatch)

**Mode Detection:**
- **Online:** Screens, video calls, virtual backgrounds, remote participants
- **Offline:** Physical venue, in-person attendees, physical setup

#### 5.5 20+ Participants Visible (4 points)

**Function:** `validate_20_plus_participants_visible()`

**Process:**
1. **Extract from Analysis:**
   - Uses `analysis["has_20_plus_participants"]` from single API call
   - Also uses `analysis["participant_count_estimate"]` for logging

2. **Scoring:**
   - **PASS:** 4 points (20+ participants visible in image)
   - **FAIL:** 0 points (<20 participants visible)

**Note:** Geotag validation is **DISABLED** per user request.

---

### 6. Duplicate Validation

**Function:** `validate_duplicate_detection()`

**Location:** `event_validator/validators/duplicate_validator.py`

**Total Points:** 15

#### 6.1 Batch-Level Duplicate Detection

**Process:**
1. **SHA256 Hash Check:**
   - Compares current image SHA256 with all previous submissions in batch
   - Uses global `_batch_hash_tracker` dictionary
   - Exact match = duplicate

2. **pHash Similarity Check:**
   - If SHA256 doesn't match, checks pHash similarity
   - Calculates Hamming distance between pHashes
   - If distance ≤ `phash_threshold` (default: 5) = duplicate

3. **Tracking:**
   - Stores all image hashes in `_batch_hash_tracker`
   - Format: `{sha256: {submission_id, phash, file_path}}`

#### 6.2 Directory-Level Duplicate Detection

**Process:**
1. **Directory Scanning:**
   - Scans entire `event_driven` directory (if `base_image_path` configured)
   - Uses `blob_directory_scanner` to find all images
   - Checks against all images in the directory, not just current batch

2. **Path Resolution:**
   - Uses `event_driven` and `academic_year` to construct directory path
   - Scans recursively for all image files

3. **Hash Comparison:**
   - SHA256 exact match
   - pHash similarity (Hamming distance ≤ threshold)

#### 6.3 Scoring

**Scoring:**
- **PASS:** 15 points (no duplicates found)
- **FAIL:** 0 points (duplicate found)

**Duplicate Message Format:**
- Batch duplicate: `"Duplicate Check: Image identical to submission {id} (SHA256 match)"`
- Directory duplicate: `"Duplicate Check: Image similar to {file_path} (pHash distance: {distance})"`

**Note:** If no images provided, returns PASS (15 points) with message "No images provided (no duplicates possible)".

---

## API Calls and Rate Limiting

### API Call Flow

#### Text Analysis (Gemini)

**Model:** `gemini-2.0-flash-exp`

**Calls Per Submission:**
1. Theme alignment check: **1 call**
2. PDF title match: **1 call**
3. PDF expert details: **1 call**
4. PDF learning outcomes: **1 call**
5. PDF objectives: **1 call**
6. PDF participant info: **1 call**

**Total Text Calls:** 6 per submission

#### Vision Analysis (Gemini)

**Model:** `gemini-2.5-pro`

**Calls Per Submission:**
1. Image analysis (single call for all 4 checks): **1 call per image**

**Total Vision Calls:** 1 per image (typically 1-2 images = 1-2 calls)

#### Total API Calls Per Submission

- **Minimum:** 7 calls (1 image, all validations)
- **Typical:** 8 calls (2 images, all validations)
- **Maximum:** 9+ calls (3+ images, all validations)

### Rate Limiting

**Implementation:** `TokenBucketRateLimiter`

**Location:** `event_validator/utils/rate_limiter.py`

**Configuration:**
- **Default RPM:** 13 requests/minute (90% of 15 RPM limit)
- **Safety Factor:** 0.9 (10% buffer)
- **Burst Size:** 13 requests

**How It Works:**
1. **Token Bucket Algorithm:**
   - Tracks request timestamps in sliding 60-second window
   - Calculates delay needed before next request
   - Ensures never exceeding RPM limit

2. **Dynamic Delay Calculation:**
   ```python
   if requests_in_last_minute >= RPM_limit:
       delay = time_until_oldest_request_expires + 0.1s
   else:
       delay = min_interval_between_requests
   ```

3. **Automatic Throttling:**
   - Acquires semaphore before API call
   - Calculates and waits for required delay
   - Logs delay for debugging

**Rate Limit Detection:**
- Detects 429 errors, quota exceeded, resource_exhausted
- Switches to sequential processing mode
- Uses exponential backoff: 5s, 10s, 20s (max 60s)
- Falls back to Groq only after all Gemini retries fail

### Groq Fallback

**Trigger Conditions:**
1. Gemini API completely unavailable (network error)
2. All Gemini retry attempts failed (3 retries)
3. Rate limit exceeded and backoff exhausted

**Fallback Process:**
1. Logs warning: "All Gemini API retry attempts failed, trying Groq as last resort"
2. Uses Groq client with same prompt
3. For images: Groq has limited vision capabilities (text-based analysis)
4. Returns result if successful, otherwise returns None

---

## Scoring and Status Determination

### Score Calculation

**Location:** `event_validator/orchestration/runner.py:256-275`

**Process:**
1. **Sum All Validation Points:**
   ```python
   total_points = sum(r.points_awarded for r in all_results)
   submission.overall_score = total_points
   ```

2. **Score Breakdown:**
   - Theme: 0-33 points (Year alignment disabled)
   - PDF: 0-25 points
   - Image: 0-14 points (Geotag disabled)
   - Duplicate: 0-15 points
   - **Total Maximum:** 87 points

3. **Logging:**
   - Logs score breakdown by category
   - Shows passed/failed rules count
   - Displays total score

### Status Determination

**Location:** `event_validator/orchestration/runner.py:277-295`

**Priority Order:**

#### 1. Mandatory File Check (Highest Priority)

```python
if pdf_missing:
    submission.status = "Reopen"
elif images_missing:
    submission.status = "Reopen"
```

**Status:** `Reopen`
- **Trigger:** PDF missing OR no images available
- **Score:** Ignored (status overrides score)
- **Message:** "PDF is mandatory but missing" or "At least 1 image is mandatory but missing"

#### 2. Score-Based Status

```python
elif total_points >= threshold:
    submission.status = "Accepted"
else:
    submission.status = "Rejected"
```

**Status:** `Accepted`
- **Condition:** Score ≥ `acceptance_threshold` (default: 60)
- **Mandatory files:** Present

**Status:** `Rejected`
- **Condition:** Score < `acceptance_threshold`
- **Mandatory files:** Present

#### 3. Error Status

**Status:** `Error`
- **Trigger:** Exception during processing
- **Score:** 0
- **Message:** Error details in "Requirements Not Met"

### Requirements Not Met Message

**Location:** `event_validator/orchestration/runner.py:296-323`

**Format:** Semicolon-separated list of failed validations

**Generation:**
1. Iterates through all validation results
2. Collects failed validations (where `passed = False`)
3. Formats as: `"Rule Name; Rule Name; ..."`
4. Includes detailed reasons for each failure

**Example:**
```
"Title/Objectives/Learning align to theme; PDF title matches metadata; Expert details present; Learning outcomes align; Objectives match; Participant info matches; Banner/Poster visible; Event scene is real activity; Event mode matches (online/offline); 20+ participants visible"
```

---

## Output Generation

### CSV Output Format

**Location:** `event_validator/orchestration/runner.py:392-404`

**Process:**
1. **Preserve Original Columns:**
   - All original CSV columns are kept
   - Original data is stored in `_original_row_data`

2. **Add New Columns:**
   - `Overall Score`: Integer (0-87)
   - `Status`: String ("Accepted", "Rejected", "Reopen", "Error")
   - `Requirements Not Met`: String (semicolon-separated list)

3. **Field Ordering:**
   - Original fields first
   - New fields appended at end
   - Duplicates removed (if any)

4. **Encoding:**
   - UTF-8-sig (includes BOM for Excel compatibility)
   - Ensures proper display in Excel

### Output File Location

**Default:** `./outputs/validation_results_{input_name}_{timestamp}.csv`

**Example:** `./outputs/validation_results_output_20260122_130620.csv`

**Naming Convention:**
- Base name from input file (sanitized)
- Timestamp: `YYYYMMDD_HHMMSS`
- Extension: `.csv`

### Error Handling in Output

**Process:**
1. **Successful Processing:**
   - Original row data + Score + Status + Requirements Not Met

2. **Error During Processing:**
   - Original row data preserved
   - Score: 0
   - Status: "Error"
   - Requirements Not Met: "Processing error: {error_message}"

3. **Missing Files:**
   - Processing continues
   - Validations that require files return 0 points
   - Status set to "Reopen" if mandatory files missing

---

## Performance Characteristics

### Processing Time Per Submission

**Breakdown:**
- File downloads: 5-10 seconds (depends on file size and network)
- Theme validation: ~1 second (1 API call)
- PDF validation: ~5-8 seconds (5 API calls with rate limiting)
- Image validation: ~8 seconds per image (1 API call per image, optimized)
- Duplicate validation: <1 second (local hash comparison)
- **Total:** ~20-30 seconds per submission (with 2 images)

### Rate Limiting Impact

**Without Rate Limiting:**
- Would hit API limits quickly
- Risk of 429 errors and temporary bans

**With Rate Limiting:**
- Smooth processing at 13 RPM
- Automatic delay calculation
- Prevents rate limit errors

### Optimization Benefits

**Image Validation Optimization:**
- **Before:** 4 API calls per image = ~32 seconds
- **After:** 1 API call per image = ~8 seconds
- **Improvement:** 4x faster image validation

---

## Error Handling and Resilience

### Network Errors

**Handling:**
1. **Retry Logic:**
   - 3 retry attempts with exponential backoff
   - Extracts retry delay from error messages if available

2. **Fallback:**
   - Groq fallback after all Gemini retries fail
   - Continues processing even if one API call fails

3. **Graceful Degradation:**
   - Missing files don't crash the system
   - Failed validations return 0 points but processing continues

### File Download Errors

**Handling:**
1. **404 Errors:**
   - Logs warning
   - Marks file as missing
   - Continues with other validations

2. **Network Timeouts:**
   - Retries with exponential backoff
   - Marks as missing if all retries fail

3. **Invalid Files:**
   - Logs error
   - Skips file
   - Continues processing

### API Response Parsing

**Handling:**
1. **Malformed Responses:**
   - Defaults to False/0 points
   - Logs warning
   - Continues processing

2. **Missing Fields:**
   - Uses default values
   - Validates response format
   - Handles gracefully

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | Required | Google Gemini API key |
| `GROQ_API_KEY` | Optional | Groq API key for fallback |
| `ACCEPTANCE_THRESHOLD` | 60 | Minimum score for acceptance |
| `PHASH_THRESHOLD` | 5 | pHash Hamming distance threshold |
| `BASE_IMAGE_PATH` | None | Base directory f