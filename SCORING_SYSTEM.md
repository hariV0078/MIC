# Event Validation System - Scoring System

## Overview

The Event Validation System uses a **100-point scoring system** to evaluate event submissions. Each submission is validated across four main categories: Theme Validation, PDF Validation, Image Validation, and Similarity/Duplicate Detection.

**Acceptance Threshold:** 60 points (submissions scoring ≥60 are accepted)

---

## Scoring Breakdown

### 1. Theme Validation (40 points total)

Validates the alignment of event content with declared theme and basic requirements.

| Rule | Points | Description |
|------|--------|-------------|
| **Title/Objectives/Learning align to theme** | 10 | Uses AI (Gemini) to check semantic alignment between event title, objectives, learning outcomes, and declared theme. Event-driven policy: event_driven 1,2,4 validate against canonical title; event_driven 3 validates user-provided title. |
| **Level matches duration** | 11 | Validates that the event Level (1-4) matches the event duration. Auto-corrects Level if it doesn't match duration. Level definitions: Level 1 (2-4h), Level 2 (5-8h), Level 3 (9-18h), Level 4 (19+h). |
| **Participants reported > 15** | 12 | Checks if the number of participants reported exceeds 15. Rule-based validation (no AI required). |
| **Year alignment (financial vs academic)** | 7 | **DISABLED** - Currently not validated per user requirements. |

**Total Theme Points:** 33 points (Year alignment disabled)

---

### 2. PDF Validation (25 points total)

Validates PDF content against expected metadata and requirements.

| Rule | Points | Description |
|------|--------|-------------|
| **PDF title matches metadata** | 7 | Uses AI to check if PDF title/header matches expected event title (fuzzy matching). |
| **Expert details present** | 7 | Checks for expert/speaker/facilitator details in PDF using keyword matching and AI validation. Keywords: expert, speaker, facilitator, instructor, trainer, resource person, keynote, presenter, panelist. |
| **Learning outcomes align** | 3 | Uses AI to check semantic alignment between PDF learning outcomes and expected learning outcomes. |
| **Objectives match** | 3 | Uses AI to check semantic alignment between PDF objectives and expected objectives. |
| **Participant info matches** | 5 | Uses AI to validate that PDF participant information matches expected count (15+ participants). |

**Total PDF Points:** 25 points

**Optimization:** All 5 PDF validations are performed in a single unified API call for efficiency.

---

### 3. Image Validation (20 points total)

Validates event images for authenticity, content, and requirements.

| Rule | Points | Description |
|------|--------|-------------|
| **GeoTag present** | 6 | **DISABLED** - Currently not validated per user requirements. |
| **Banner/Poster visible** | 2 | Uses AI vision to check if event banner or poster is visible in images. |
| **Event scene is real activity** | 3 | Uses AI vision to verify that images depict a real event activity (not stock photos or unrelated images). |
| **Event mode matches (online/offline)** | 5 | Uses AI vision to verify that images match the declared event mode (online vs offline). |
| **15+ participants visible** | 4 | Uses AI vision to count and verify that 15 or more participants are visible in images. |

**Total Image Points:** 14 points (Geotag validation disabled)

**Optimization:** All image validations use a single AI vision API call per image.

---

### 4. Similarity/Duplicate Detection (15 points total)

Detects duplicate or near-duplicate images within batch and across directory.

| Rule | Points | Description |
|------|--------|-------------|
| **Duplicate photo detection (filesystem)** | 15 | Checks for duplicate images using: 1) SHA256 exact match (batch and directory-level), 2) pHash near-duplicate detection (configurable threshold, default 10 Hamming distance). Scans both current batch and event_driven directory. |

**Total Similarity Points:** 15 points

---

## Scoring Summary

| Category | Points | Status |
|----------|--------|--------|
| Theme Validation | 33 | Year alignment disabled |
| PDF Validation | 25 | All active |
| Image Validation | 14 | Geotag disabled |
| Similarity Detection | 15 | All active |
| **TOTAL** | **87** | **Max possible with current configuration** |

**Note:** The theoretical maximum is 100 points, but with Year alignment (7 points) and Geotag (6 points) disabled, the practical maximum is **87 points**.

---

## Acceptance Criteria

- **Accepted:** Score ≥ 60 points AND all mandatory requirements met
- **Rejected:** Score < 60 points
- **Reopen:** Mandatory files missing (PDF is mandatory, at least 1 image is mandatory)

### Mandatory Requirements

1. **PDF file** - Must be present and readable
2. **At least 1 image** - Must be present and valid

If either mandatory requirement is missing, the submission status is set to **"Reopen"** regardless of score.

---

## Level-Duration Matching Rules

The system uses the following level definitions for auto-correction:

| Level | Duration Range | Event Types | Description |
|-------|----------------|-------------|-------------|
| **1** | 2-4 hours | Expert Talk, Mentoring Session, Exposure Visit | Less than half a day |
| **2** | 5-8 hours | Seminar, Workshop, Conference, Exposure Visit, Panel Discussion, Roundtable Discussion, Networking Event | One Full day |
| **3** | 9-18 hours | Boot Camp, Workshop, Exhibition/Startup Showcase, Demo Day, Competition, Hackathons, Conference | More than one day |
| **4** | 19+ hours | Challenge, Tech/E-Fest, Hackathon, Competition, Workshop, Boot Camp, Exhibition/Startup Showcase | More than 2 days |

**Auto-Correction Logic:**
- If Level is empty but Duration is valid → Auto-determine Level from Duration
- If Level doesn't match Duration → Auto-correct Level to match Duration
- If Duration is invalid or Level cannot be determined → Validation fails (0 points)

---

## Scoring Logic

### Binary Scoring
- Each rule is scored **binary**: Full points if passed, 0 points if failed
- No partial credit is awarded

### Pre-Scoring Gate (Heuristic)
Before expensive AI calls, the system performs quick heuristic checks:
- PDF presence and basic keyword checks
- Image presence
- Participants count (>15)
- Level-duration match (rule-based)
- Basic field presence (theme, objectives, learning outcomes)

This helps identify weak submissions early and can save 30-50% of API calls.

### Requirements Not Met Message
Failed validations are compiled into a "Requirements Not Met" message, listing all failed criteria with reasons.

---

## API Usage

### Theme Validation
- **1 API call** per submission (Gemini for semantic alignment)

### PDF Validation
- **1 unified API call** per submission (Gemini for all 5 checks)

### Image Validation
- **1 API call** per submission (Gemini Vision for all 4 checks, uses first image)

### Duplicate Detection
- **0 API calls** (uses SHA256 and pHash hashing, no AI required)

**Total API calls per submission:** 3 calls (Theme + PDF + Image)

---

## Performance Optimizations

1. **Unified PDF Validation:** 5 separate checks combined into 1 API call
2. **Unified Image Validation:** 4 separate checks combined into 1 API call
3. **Heuristic Pre-scoring:** Early filtering of weak submissions
4. **Parallel Processing:** Multiple submissions processed concurrently
5. **Rate Limiting:** Token bucket algorithm prevents API rate limit errors
6. **Caching:** API responses cached to avoid duplicate calls
7. **Circuit Breaker:** Prevents cascading failures when APIs are down

---

## Recent Changes

- **Participant threshold:** Changed from 20 to 15 (affects Theme rule "Participants reported > 15" and Image rule "15+ participants visible")
- **Level auto-correction:** Added feature to auto-correct Level if it doesn't match Duration
- **Year alignment:** Disabled (7 points not awarded)
- **Geotag validation:** Disabled (6 points not awarded)
