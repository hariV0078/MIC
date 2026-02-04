# Event Validator Validation Rules (as of 2026-02-04)

## Overview
The Event Validator performs comprehensive validation across 4 categories with a total of 100 points. Events must score 60+ points to pass validation.

- **Theme Validation**: 40 points (4 criteria)
- **PDF Validation**: 25 points (5 criteria)
- **Image Validation**: 20 points (5 criteria)
- **Similarity/Duplicate Detection**: 15 points (1 criterion)

---

## 1. Theme Validation (40 points total)

### 1.1 Title/Objectives/Learning Outcomes Alignment (10 points)
**Purpose**: Validates semantic alignment between event content and declared theme.

**Validation Logic**:
- Uses AI-powered semantic analysis to check alignment
- Combines Title, Objectives, and Learning Outcomes for comprehensive evaluation
- Event-driven title policy:
  - `event_driven 1, 2, 4`: Validates against canonical/generated title
  - `event_driven 3`: Validates user-provided title against theme

**Pass Criteria**: Content semantically aligns with declared theme
**Fail Criteria**: Content does not align with theme (provides reasoning)

### 1.2 Level Matches Duration (11 points)
**Purpose**: Ensures event level corresponds to duration requirements.

**Level Definitions**:
- **Level 1**: 1-2 hours
- **Level 2**: 3-4 hours
- **Level 3**: 5-8 hours
- **Level 4**: 9+ hours

**Validation Logic**:
- Parses duration from various formats ("3h", "2 hours", "180 minutes")
- Auto-corrects level if duration doesn't match declared level
- Auto-determines level from duration if level is missing

**Pass Criteria**: Level matches duration range OR level is auto-corrected
**Fail Criteria**: Duration doesn't match level requirements

### 1.3 Participants Reported (12 points - graduated scoring)
**Purpose**: Validates minimum participant threshold with graduated scoring.

**Scoring Scale**:
- **20+ participants**: 12.0 points (full score)
- **19 participants**: 11.4 points
- **18 participants**: 10.8 points
- **17 participants**: 10.2 points
- **16 participants**: 9.6 points
- **15 participants**: 9.0 points
- **< 15 participants**: 0.0 points (fail)

**Pass Criteria**: ≥ 15 participants reported
**Fail Criteria**: < 15 participants reported

### 1.4 Year Alignment (7 points) - DISABLED
**Status**: Currently disabled per user requirements
**Reason**: User provides explicit dates and academic/financial year - no validation needed against current date

---

## 2. PDF Validation (25 points total)

### Special Cases
#### MIC Events Auto-Pass
- **Trigger**: Event Type, Theme, or Title contains "MIC", "MIC-IIC", or "MIC IIC"
- **Result**: All PDF validations automatically pass (25 points)

#### Event Driven 3 Title Mismatch Hard Fail
- **Trigger**: `event_driven == 3` AND PDF title does not match expected title
- **Result**: ALL PDF validations fail (0 points total)
- **Implementation**: Multi-layer check - quick heuristic + AI confirmation

### 2.1 PDF Title Matches Metadata (7 points)
**Purpose**: Validates PDF title matches the expected event title.

**Validation Logic**:
- AI-powered fuzzy title matching
- Compares PDF extracted title against metadata title
- Considers semantic equivalence

**Pass Criteria**: PDF title matches expected title
**Fail Criteria**: PDF title does not match

### 2.2 Expert Details Present (7 points)
**Purpose**: Ensures PDF contains information about event experts/facilitators.

**Validation Logic**:
- Hybrid approach: Heuristic keyword search + AI validation
- Keywords: expert, speaker, facilitator, instructor, trainer, resource person, keynote, presenter, panelist
- Name pattern detection: "Dr. Name", "Prof. Name", "First Last"

**Pass Criteria**: Expert mentions or name patterns found in PDF
**Fail Criteria**: No expert information found

### 2.3 Learning Outcomes Align (3 points)
**Purpose**: Validates learning outcomes in PDF match expected outcomes.

**Validation Logic**:
- AI-powered semantic alignment check
- Rule-based heuristic: Must contain 2+ learning-related keywords AND title must match
- Keywords: learning, outcome, benefit, knowledge, skill, understand, ability, competency

**Pass Criteria**: Learning outcomes align with expected AND title matches
**Fail Criteria**: Learning outcomes don't align OR title mismatch

### 2.4 Objectives Match (3 points)
**Purpose**: Validates objectives in PDF match expected objectives.

**Validation Logic**:
- AI-powered semantic alignment check
- Rule-based validation using regex and pattern matching

**Pass Criteria**: Objectives in PDF match expected objectives
**Fail Criteria**: Objectives don't match

### 2.5 Participant Info Matches (5 points)
**Purpose**: Validates participant numbers in PDF are sufficient.

**Validation Logic**:
- Hybrid approach: Regex extraction + AI fallback
- Regex looks for numbers near participant-related terms
- Minimum threshold: 15+ participants

**Pass Criteria**: PDF indicates 15+ participants
**Fail Criteria**: PDF shows < 15 participants or no participant information

---

## 3. Image Validation (20 points total)

### 3.1 GeoTag Present (6 points)
**Purpose**: Ensures images contain location metadata.

**Validation Logic**:
- Checks EXIF data for GPS coordinates
- At least one image in submission must have geotag

**Pass Criteria**: At least one image has geotag
**Fail Criteria**: No images have geotag

### 3.2 Banner/Poster Visible (2 points)
**Purpose**: Validates event branding is visible in images.

**Validation Logic**:
- AI-powered image analysis
- Looks for event banners, posters, or branding elements

**Pass Criteria**: Banner or poster visible in images
**Fail Criteria**: No banner/poster visible

### 3.3 Event Scene is Real Activity (3 points)
**Purpose**: Ensures images show actual event activities, not just setup or empty rooms.

**Validation Logic**:
- AI-powered scene analysis
- Distinguishes between active event scenes and non-event images

**Pass Criteria**: Images show real event activities
**Fail Criteria**: Images show setup, empty rooms, or non-event scenes

### 3.4 Event Mode Matches (5 points)
**Purpose**: Validates images match declared event mode (online/offline).

**Validation Logic**:
- AI analysis of image content vs. metadata event mode
- Checks for online indicators (screens, virtual backgrounds) vs. offline indicators (physical venues, crowds)

**Pass Criteria**: Image content matches declared event mode
**Fail Criteria**: Image content contradicts event mode

### 3.5 15+ Participants Visible (4 points)
**Purpose**: Ensures images show sufficient participant attendance.

**Validation Logic**:
- AI-powered crowd counting and participant detection
- Minimum threshold: 15+ participants visible

**Pass Criteria**: Images show 15+ participants
**Fail Criteria**: Images show < 15 participants

---

## 4. Similarity/Duplicate Detection (15 points total)

### 4.1 Duplicate Photo Detection (15 points)
**Purpose**: Prevents submission of duplicate or reused images.

**Validation Logic**:
- **Batch-level detection**: Checks for duplicates within current validation batch
- **Directory-level detection**: Scans across all submissions in event_driven directory
- **Multi-hash approach**:
  - SHA256 exact matches
  - pHash perceptual hashing for near-duplicates (configurable threshold)
- **Same-submission duplicates**: Ignored (multiple images from same report are allowed)

**Pass Criteria**: No duplicate images found across submissions
**Fail Criteria**: Duplicate images detected (provides details of matches)

---

## Scoring and Acceptance

### Total Points Distribution
- **Theme**: 40 points (40%)
- **PDF**: 25 points (25%)
- **Image**: 20 points (20%)
- **Similarity**: 15 points (15%)
- **Total**: 100 points

### Acceptance Threshold
- **Pass**: ≥ 60 points
- **Fail**: < 60 points

### Special Scoring Notes
- Participant validation uses graduated scoring (not binary)
- Some validations auto-correct data (e.g., level based on duration)
- MIC events get automatic PDF validation pass
- Event Driven 3 with title mismatch causes total PDF validation failure

---

## Technical Implementation Notes

### AI Integration
- Uses Ollama for semantic analysis and content validation
- Caching system prevents redundant API calls
- Circuit breaker pattern for API reliability

### Validation Flow
1. **Pre-checks**: Quick heuristic validations
2. **AI Analysis**: Semantic content analysis where needed
3. **Rule-based**: Structured validation with clear pass/fail criteria
4. **Scoring**: Point allocation based on validation results

### Data Sources
- **Primary**: `activity_name` field (event title)
- **Fallback**: `Title` field if `activity_name` empty
- **Original Data**: `_original_row_data` for event metadata
- **Event Driven**: Determines title validation policy

---

_Last updated: 2026-02-04_
