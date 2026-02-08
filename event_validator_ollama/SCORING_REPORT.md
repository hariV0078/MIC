# 📊 MIC Event Validation & Scoring Report

**Total Points: 100** | **Pass Threshold: 55 points**

---

## ✅ YES - The Code Has Full Validation

The codebase contains **complete validation** for all categories:
- Theme validation (with level/participants)
- PDF validation
- Image validation  
- Duplicate detection

---

## Complete Validation Flow

## Complete Validation Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         START: process_submission()                          │
│                    (orchestration/runner.py line 158)                        │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  1. DOWNLOAD & EXTRACT FILES                                                 │
│  ────────────────────────────                                                │
│  • Download PDF from Azure Blob Storage                                      │
│  • Download Images (supports multiple)                                       │
│  • Extract text from PDF (pdfplumber)                                        │
│  • Extract image metadata (EXIF, GeoTag)                                     │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  2. PRE-SCORING GATE (Heuristic Check)                                       │
│  ─────────────────────────────────────                                       │
│  Quick rule-based checks before AI calls:                                    │
│  • Expert keywords in PDF? (+7)                                              │
│  • Images present? (+2)                                                      │
│  • Participants > 15? (+12)                                                  │
│  • Level matches duration? (+11)                                             │
│  • Theme/Objectives/Learning present? (+5)                                   │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  3. THEME VALIDATION (40 points)                                             │
│  ───────────────────────────────                                             │
│  validators/theme_validator.py → validate_theme()                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ [1] Title matches theme                         │ 20 pts │ AI     │     │
│  │ [2] Level matches duration                      │ 10 pts │ Rules  │     │
│  │ [3] Participants reported > 15                  │ 10 pts │ Rules  │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  4. PDF VALIDATION (20 points)                                               │
│  ─────────────────────────────                                               │
│  validators/pdf_validator.py → validate_pdf()                                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ [1] PDF title matches metadata                  │  7 pts │ AI     │     │
│  │ [2] Expert details present                      │  7 pts │ Rules  │     │
│  │ [3] Objectives and learning align               │  6 pts │ AI     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ⚠️ Special: event_driven=3 → if theme fails, PDF fails too                  │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  5. IMAGE VALIDATION (20 points)                                             │
│  ──────────────────────────────                                              │
│  validators/image_validator.py → validate_images()                           │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ [1] GeoTag present                              │  5 pts │ EXIF   │     │
│  │ [2] Banner/Poster visible                       │  5 pts │ Vision │     │
│  │ [3] Event scene is real activity                │  5 pts │ Vision │     │
│  │ [4] 15+ participants visible                    │  5 pts │ Vision │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  Uses Ollama Vision (llava:latest) for image analysis                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  6. DUPLICATE VALIDATION (20 points)                                         │
│  ───────────────────────────────────                                         │
│  validators/duplicate_validator.py → validate_duplicates()                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ [1] Duplicate image check                       │ 10 pts │ Hash   │     │
│  │ [2] Duplicate title check                       │ 10 pts │ Rule   │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  • Duplicate Image: -10 points on fail                                       │
│  • Duplicate Title: -10 points on fail (Same User + Same Title)              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
│  7. SCORING & STATUS                                                         │
│  ───────────────────                                                         │
│  Total Score = Theme + PDF + Image + Duplicate                               │
│                                                                              │
│  Status Decision:                                                            │
│  • PDF missing? → "Reopen"                                                   │
│  • Images missing? → "Reopen"                                                │
│  • Score >= 60? → "Accepted"                                                 │
│  • Score < 60? → "Rejected"                                                  │
│  • Mandatory Rejection: Duplicate Title/Image                                │
119: └──────────────────────────────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              [DONE]
```

---

## Scoring Summary

| Category | Max Points | Validator File |
|----------|-----------|----------------|
| Theme Validation | 40 | `theme_validator.py` |
| PDF Validation | 20 | `pdf_validator.py` |
| Image Validation | 20 | `image_validator.py` |
| Duplicate Check | 20 | `duplicate_validator.py` |
| **TOTAL** | **100** | |

---

## Key Files

| File | Purpose |
|------|---------|
| `orchestration/runner.py` | Main orchestration - calls all validators |
| `validators/ollama_client.py` | LLM API calls (Ollama) |
| `validators/theme_validator.py` | Theme/Level/Participants checks |
| `validators/pdf_validator.py` | PDF content validation |
| `validators/image_validator.py` | Image/Vision validation |
| `validators/duplicate_validator.py` | Duplicate detection |
| `config/rules.py` | Points configuration |
