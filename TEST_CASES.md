# Event Validation System - Test Cases

## Overview

This document outlines test cases for the Event Validation System, covering all validation categories and edge cases.

---

## Test Case Categories

1. [Theme Validation Test Cases](#theme-validation-test-cases)
2. [PDF Validation Test Cases](#pdf-validation-test-cases)
3. [Image Validation Test Cases](#image-validation-test-cases)
4. [Duplicate Detection Test Cases](#duplicate-detection-test-cases)
5. [Level-Duration Matching Test Cases](#level-duration-matching-test-cases)
6. [Integration Test Cases](#integration-test-cases)
7. [Edge Cases](#edge-cases)

---

## Theme Validation Test Cases

### TC-THEME-001: Title/Objectives/Learning Align to Theme (10 points)

**Test Case:** Valid theme alignment
- **Input:** 
  - Theme: "Digital Transformation"
  - Title: "Workshop on Digital Transformation in Education"
  - Objectives: "Understand digital tools for education"
  - Learning Outcomes: "Participants will learn about digital tools"
  - Event Driven: 1
- **Expected:** PASS (10 points)
- **AI Check:** Semantic alignment confirmed

**Test Case:** Invalid theme alignment
- **Input:**
  - Theme: "Digital Transformation"
  - Title: "Cooking Workshop"
  - Objectives: "Learn cooking techniques"
  - Learning Outcomes: "Participants will learn cooking"
  - Event Driven: 1
- **Expected:** FAIL (0 points)
- **AI Check:** Content does not align with theme

**Test Case:** Missing theme
- **Input:**
  - Theme: ""
  - Title: "Workshop on AI"
- **Expected:** FAIL (0 points)
- **Message:** "Theme missing — cannot validate alignment"

---

### TC-THEME-002: Level Matches Duration (11 points)

**Test Case:** Valid level-duration match
- **Input:**
  - Level: 2
  - Duration: "6h"
  - Event Type: "Workshop"
- **Expected:** PASS (11 points)
- **Note:** Level 2 requires 5-8 hours

**Test Case:** Level auto-correction (mismatch)
- **Input:**
  - Level: 1
  - Duration: "6h"
  - Event Type: "Workshop"
- **Expected:** PASS (11 points)
- **Note:** Level auto-corrected from 1 to 2

**Test Case:** Level auto-determination (empty level)
- **Input:**
  - Level: ""
  - Duration: "6h"
  - Event Type: "Workshop"
- **Expected:** PASS (11 points)
- **Note:** Level auto-determined as 2

**Test Case:** Invalid duration
- **Input:**
  - Level: 2
  - Duration: ""
- **Expected:** FAIL (0 points)
- **Message:** "Duration missing/invalid"

**Test Case:** Level cannot be determined
- **Input:**
  - Level: ""
  - Duration: "1h"
- **Expected:** FAIL (0 points)
- **Message:** "Level missing and cannot be determined from duration 1.0h"
- **Note:** 1h is below minimum for any level (Level 1 requires 2-4h)

---

### TC-THEME-003: Participants Reported > 15 (12 points)

**Test Case:** Valid participant count
- **Input:**
  - Participants: "20"
- **Expected:** PASS (12 points)

**Test Case:** Invalid participant count (exactly 15)
- **Input:**
  - Participants: "15"
- **Expected:** FAIL (0 points)
- **Message:** "Participants reported: 15 (needs > 15)"
- **Note:** Must be strictly greater than 15

**Test Case:** Invalid participant count (below 15)
- **Input:**
  - Participants: "10"
- **Expected:** FAIL (0 points)

**Test Case:** Missing participants
- **Input:**
  - Participants: ""
- **Expected:** FAIL (0 points)
- **Note:** Treated as 0

**Test Case:** Invalid format
- **Input:**
  - Participants: "abc"
- **Expected:** FAIL (0 points)
- **Note:** Treated as 0

---

### TC-THEME-004: Year Alignment (7 points)

**Test Case:** Year alignment validation
- **Status:** DISABLED
- **Note:** Currently not validated per user requirements

---

## PDF Validation Test Cases

### TC-PDF-001: PDF Title Matches Metadata (7 points)

**Test Case:** Valid title match
- **Input:**
  - Expected Title: "Workshop on AI"
  - PDF Text: Contains "Workshop on AI" or similar
- **Expected:** PASS (7 points)
- **AI Check:** Fuzzy title matching

**Test Case:** Invalid title match
- **Input:**
  - Expected Title: "Workshop on AI"
  - PDF Text: Contains "Cooking Workshop"
- **Expected:** FAIL (0 points)
- **Message:** "PDF title does not match expected title: Workshop on AI"

**Test Case:** Missing PDF
- **Input:**
  - PDF: Not provided or unreadable
- **Expected:** FAIL (0 points)
- **Message:** "PDF text not extracted"

---

### TC-PDF-002: Expert Details Present (7 points)

**Test Case:** Expert details found (keyword)
- **Input:**
  - PDF Text: Contains "expert", "speaker", "facilitator", etc.
- **Expected:** PASS (7 points)

**Test Case:** Expert details found (name pattern)
- **Input:**
  - PDF Text: Contains "Dr. John Smith" or "Prof. Jane Doe"
- **Expected:** PASS (7 points)

**Test Case:** Expert details not found
- **Input:**
  - PDF Text: No expert-related keywords or name patterns
- **Expected:** FAIL (0 points)
- **Message:** "Expert details not found in PDF"

---

### TC-PDF-003: Learning Outcomes Align (3 points)

**Test Case:** Valid alignment
- **Input:**
  - Expected Learning Outcomes: "Understand AI concepts"
  - PDF Text: Contains semantically similar learning outcomes
- **Expected:** PASS (3 points)
- **AI Check:** Semantic alignment

**Test Case:** Invalid alignment
- **Input:**
  - Expected Learning Outcomes: "Understand AI concepts"
  - PDF Text: Contains unrelated learning outcomes
- **Expected:** FAIL (0 points)
- **Message:** "Learning outcomes in PDF do not align with expected outcomes"

---

### TC-PDF-004: Objectives Match (3 points)

**Test Case:** Valid match
- **Input:**
  - Expected Objectives: "Learn AI tools"
  - PDF Text: Contains semantically similar objectives
- **Expected:** PASS (3 points)
- **AI Check:** Semantic alignment

**Test Case:** Invalid match
- **Input:**
  - Expected Objectives: "Learn AI tools"
  - PDF Text: Contains unrelated objectives
- **Expected:** FAIL (0 points)
- **Message:** "Objectives in PDF do not match expected objectives"

---

### TC-PDF-005: Participant Info Matches (5 points)

**Test Case:** Valid participant count (15+)
- **Input:**
  - Expected Participants: 20
  - PDF Text: Contains participant information indicating 20+ participants
- **Expected:** PASS (5 points)
- **AI Check:** Validates participant count in PDF

**Test Case:** Invalid participant count (<15)
- **Input:**
  - Expected Participants: 20
  - PDF Text: Contains participant information indicating <15 participants
- **Expected:** FAIL (0 points)
- **Message:** "PDF participant information does not match expected (needs 15+ participants)"

---

## Image Validation Test Cases

### TC-IMAGE-001: GeoTag Present (6 points)

**Test Case:** Geotag validation
- **Status:** DISABLED
- **Note:** Currently not validated per user requirements

---

### TC-IMAGE-002: Banner/Poster Visible (2 points)

**Test Case:** Banner visible
- **Input:**
  - Image: Contains event banner or poster
- **Expected:** PASS (2 points)
- **AI Check:** Vision analysis detects banner/poster

**Test Case:** Banner not visible
- **Input:**
  - Image: No banner or poster visible
- **Expected:** FAIL (0 points)
- **Message:** "Banner or poster not visible in images"

**Test Case:** No images
- **Input:**
  - Images: Not provided
- **Expected:** FAIL (0 points)
- **Message:** "No images provided"

---

### TC-IMAGE-003: Event Scene is Real Activity (3 points)

**Test Case:** Real event activity
- **Input:**
  - Image: Depicts actual event with participants, activities
- **Expected:** PASS (3 points)
- **AI Check:** Vision analysis confirms real activity

**Test Case:** Not real activity (stock photo)
- **Input:**
  - Image: Stock photo or unrelated image
- **Expected:** FAIL (0 points)
- **Message:** "Image does not depict a real event activity"

---

### TC-IMAGE-004: Event Mode Matches (5 points)

**Test Case:** Online mode match
- **Input:**
  - Event Mode: "Online"
  - Image: Shows online event (screens, video calls)
- **Expected:** PASS (5 points)
- **AI Check:** Vision analysis confirms online mode

**Test Case:** Offline mode match
- **Input:**
  - Event Mode: "Offline"
  - Image: Shows in-person event
- **Expected:** PASS (5 points)

**Test Case:** Mode mismatch
- **Input:**
  - Event Mode: "Online"
  - Image: Shows in-person event
- **Expected:** FAIL (0 points)
- **Message:** "Event mode in image does not match specified mode: online"

---

### TC-IMAGE-005: 15+ Participants Visible (4 points)

**Test Case:** 15+ participants visible
- **Input:**
  - Image: Shows 20+ participants clearly visible
- **Expected:** PASS (4 points)
- **AI Check:** Vision analysis counts 15+ participants

**Test Case:** <15 participants visible
- **Input:**
  - Image: Shows only 10 participants
- **Expected:** FAIL (0 points)
- **Message:** "15+ participants not visible in images"

---

## Duplicate Detection Test Cases

### TC-DUP-001: Duplicate Photo Detection (15 points)

**Test Case:** No duplicates (unique images)
- **Input:**
  - Images: Unique images not seen before
- **Expected:** PASS (15 points)

**Test Case:** Batch-level duplicate (SHA256 match)
- **Input:**
  - Image 1: SHA256 = "abc123..."
  - Image 2: SHA256 = "abc123..." (same file)
- **Expected:** FAIL (0 points)
- **Message:** "Duplicate Check: Image identical to submission X (SHA256 match)"

**Test Case:** Directory-level duplicate (SHA256 match)
- **Input:**
  - Image: SHA256 matches existing file in event_driven directory
- **Expected:** FAIL (0 points)
- **Message:** "Duplicate Check: Image identical to file in directory (SHA256 match): [path]"

**Test Case:** Near-duplicate (pHash match)
- **Input:**
  - Image 1: pHash = "abc..."
  - Image 2: pHash = "abd..." (Hamming distance ≤ 10)
- **Expected:** FAIL (0 points)
- **Message:** "Duplicate Check: Image similar to submission X (pHash distance: 5, threshold: 10)"

**Test Case:** No images
- **Input:**
  - Images: Not provided
- **Expected:** PASS (15 points)
- **Note:** No images = no duplicates possible

---

## Level-Duration Matching Test Cases

### TC-LEVEL-001: Level 1 Validation

**Test Case:** Valid Level 1
- **Input:**
  - Level: 1
  - Duration: "3h"
  - Event Type: "Expert Talk"
- **Expected:** PASS (11 points)
- **Note:** Level 1 requires 2-4 hours

**Test Case:** Invalid Level 1 (too short)
- **Input:**
  - Level: 1
  - Duration: "1h"
- **Expected:** FAIL (0 points)
- **Note:** 1h is below minimum for Level 1 (2-4h)

**Test Case:** Invalid Level 1 (too long)
- **Input:**
  - Level: 1
  - Duration: "5h"
- **Expected:** FAIL (0 points) or auto-correct to Level 2

---

### TC-LEVEL-002: Level 2 Validation

**Test Case:** Valid Level 2
- **Input:**
  - Level: 2
  - Duration: "6h"
  - Event Type: "Workshop"
- **Expected:** PASS (11 points)
- **Note:** Level 2 requires 5-8 hours

---

### TC-LEVEL-003: Level 3 Validation

**Test Case:** Valid Level 3
- **Input:**
  - Level: 3
  - Duration: "12h"
  - Event Type: "Boot Camp"
- **Expected:** PASS (11 points)
- **Note:** Level 3 requires 9-18 hours

---

### TC-LEVEL-004: Level 4 Validation

**Test Case:** Valid Level 4
- **Input:**
  - Level: 4
  - Duration: "24h"
  - Event Type: "Hackathon"
- **Expected:** PASS (11 points)
- **Note:** Level 4 requires 19+ hours

**Test Case:** Level 4 boundary (19 hours)
- **Input:**
  - Level: 4
  - Duration: "19h"
- **Expected:** PASS (11 points)
- **Note:** 19h is the minimum for Level 4

---

## Integration Test Cases

### TC-INT-001: Complete Valid Submission

**Test Case:** All validations pass
- **Input:**
  - Theme: Valid alignment
  - Level: 2, Duration: 6h (matches)
  - Participants: 20 (>15)
  - PDF: Valid with all checks passing
  - Images: Valid with all checks passing
  - Duplicates: None
- **Expected Score:** 87/87 (max with disabled validations)
- **Expected Status:** Accepted

---

### TC-INT-002: Submission Missing PDF

**Test Case:** Mandatory PDF missing
- **Input:**
  - PDF: Not provided
  - All other validations: Pass
- **Expected Score:** 62/87 (PDF points = 0)
- **Expected Status:** Reopen
- **Note:** PDF is mandatory, status set to Reopen regardless of score

---

### TC-INT-003: Submission Missing Images

**Test Case:** Mandatory images missing
- **Input:**
  - Images: Not provided
  - All other validations: Pass
- **Expected Score:** 73/87 (Image points = 0)
- **Expected Status:** Reopen
- **Note:** At least 1 image is mandatory, status set to Reopen regardless of score

---

### TC-INT-004: Low Score Submission

**Test Case:** Score below threshold
- **Input:**
  - Theme: Fails alignment (0 points)
  - Level: Invalid (0 points)
  - Participants: 10 (<15, 0 points)
  - PDF: Partial passes (10 points)
  - Images: Partial passes (5 points)
  - Duplicates: None (15 points)
- **Expected Score:** 30/87
- **Expected Status:** Rejected
- **Note:** Score < 60 threshold

---

### TC-INT-005: Borderline Score Submission

**Test Case:** Score exactly at threshold
- **Input:**
  - Theme: 20 points
  - PDF: 20 points
  - Images: 10 points
  - Duplicates: 10 points
- **Expected Score:** 60/87
- **Expected Status:** Accepted
- **Note:** Score = 60 threshold

---

## Edge Cases

### TC-EDGE-001: Empty Fields

**Test Case:** All fields empty
- **Input:**
  - Theme: ""
  - Title: ""
  - Objectives: ""
  - Learning Outcomes: ""
  - Level: ""
  - Duration: ""
  - Participants: ""
  - PDF: Not provided
  - Images: Not provided
- **Expected Score:** 0/87
- **Expected Status:** Reopen (mandatory files missing)

---

### TC-EDGE-002: Invalid Duration Formats

**Test Case:** Various duration formats
- **Input:**
  - Duration: "3h" → Valid (3 hours)
  - Duration: "180 minutes" → Valid (3 hours)
  - Duration: "2 hours" → Valid (2 hours)
  - Duration: "abc" → Invalid (0 points)
  - Duration: "" → Invalid (0 points)

---

### TC-EDGE-003: Large Participant Counts

**Test Case:** Very large participant counts
- **Input:**
  - Participants: "1000"
- **Expected:** PASS (12 points)
- **Note:** Any value > 15 passes

---

### TC-EDGE-004: Multiple Images

**Test Case:** Multiple images provided
- **Input:**
  - Images: 3 images provided
- **Expected:** Uses first image for validation
- **Note:** All validations use first image only

---

### TC-EDGE-005: PDF Extraction Failure

**Test Case:** PDF exists but cannot be extracted
- **Input:**
  - PDF: Corrupted or unreadable file
- **Expected:** FAIL (0 points for all PDF validations)
- **Message:** "PDF text not extracted"

---

### TC-EDGE-006: Image Download Failure

**Test Case:** Image URL invalid or download fails
- **Input:**
  - Image Path: Invalid URL or file not found
- **Expected:** FAIL (0 points for all image validations)
- **Message:** "Event photos missing or invalid"

---

### TC-EDGE-007: Event-Driven Title Policy

**Test Case:** event_driven 1, 2, 4 (canonical title)
- **Input:**
  - Event Driven: 1
  - Title: Validates against canonical title generated from theme/objectives
- **Expected:** PASS if canonical title matches

**Test Case:** event_driven 3 (user title)
- **Input:**
  - Event Driven: 3
  - Title: Validates user-provided title against theme
- **Expected:** PASS if user title aligns with theme

---

### TC-EDGE-008: Level Auto-Correction Edge Cases

**Test Case:** Level correction when event_type is empty
- **Input:**
  - Level: 1
  - Duration: "6h"
  - Event Type: ""
- **Expected:** PASS (11 points)
- **Note:** Level auto-corrected to 2 based on duration only

**Test Case:** Level determination when both level and event_type are empty
- **Input:**
  - Level: ""
  - Duration: "6h"
  - Event Type: ""
- **Expected:** PASS (11 points)
- **Note:** Level auto-determined as 2 from duration only

---

## Test Execution

### Unit Tests
Run unit tests for rules configuration:
```bash
python -m pytest event_validator/tests/unit/test_rules.py
```

### Integration Tests
Run integration tests for score aggregation:
```bash
python -m pytest event_validator/tests/unit/test_score_aggregation.py
```

### Manual Testing
Use test CSV files with various scenarios:
- `csv/test_data_10.csv` - Small test set
- `csv/test_data_first_1000.csv` - Larger test set

---

## Test Data Requirements

For comprehensive testing, ensure test data includes:

1. **Valid submissions** - All validations passing
2. **Invalid submissions** - Various validation failures
3. **Edge cases** - Empty fields, invalid formats, boundary conditions
4. **Missing files** - PDF missing, images missing
5. **Duplicate images** - Same image in multiple submissions
6. **Various event types** - Different event types and levels
7. **Various durations** - Boundary values (2h, 4h, 5h, 8h, 9h, 18h, 19h, etc.)
8. **Various participant counts** - 0, 15, 16, 20, 100, 1000

---

## Expected Behavior Summary

| Scenario | Score Range | Status | Notes |
|----------|-------------|--------|-------|
| All validations pass | 60-87 | Accepted | Max 87 with disabled validations |
| Score ≥ 60, all mandatory files present | 60-87 | Accepted | |
| Score < 60 | 0-59 | Rejected | |
| PDF missing | Any | Reopen | Mandatory requirement |
| Images missing | Any | Reopen | Mandatory requirement |
| PDF + Images missing | Any | Reopen | Multiple mandatory requirements missing |
