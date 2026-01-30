# Government Data Validator - Project Summary

## Overview

This is an **AI-powered event validation system** designed for government use to automatically validate and score event submissions. The system processes CSV files containing event data and validates submissions against multiple criteria using Google Gemini AI and Groq as a fallback.

## Purpose

The system validates educational/training event submissions (workshops, seminars, conferences, hackathons, etc.) to ensure they meet government quality standards. It automates the review process that would otherwise require manual inspection of PDFs, images, and metadata.

## What It Validates

### Input Data
- **CSV/XLSX files** containing event submissions with fields such as:
  - Event title, theme, objectives, learning outcomes
  - Event type, level, duration, participant counts
  - PDF report paths (Azure Blob Storage URLs or local paths)
  - Image paths (event photos)
  - Financial/academic year information
  - Event mode (online/offline)
  - Event-driven classification

### Mandatory Requirements
1. **PDF Report** - Must be present and readable
2. **At least 1 Image** - Event photos are mandatory
3. **Minimum Score** - 60/100 points to be accepted (configurable)

## Validation Categories & Scoring

The system validates submissions across **4 main categories** with a total of **100 points**:

### 1. Theme Validation (33 points)
- **Title/Objectives/Learning align to theme** (10 points)
  - Uses AI to check semantic alignment between event title, objectives, learning outcomes, and theme
  - Different validation rules based on `event_driven` type (1, 2, 3, 4)
- **Level matches duration** (11 points)
  - Validates that event level (1-4) matches the reported duration
  - Level 1: 2-4 hours, Level 2: 5-8 hours, Level 3: 9-18 hours, Level 4: 19+ hours
- **Participants reported > 20** (12 points)
  - Checks if total participants (students + faculty) exceed 20
- **Year alignment** (7 points) - Currently disabled

### 2. PDF Validation (25 points)
- **PDF title matches metadata** (7 points)
  - Extracts title from PDF and compares with submission metadata
- **Expert details present** (7 points)
  - Verifies presence of expert/speaker/facilitator information in PDF
- **Learning outcomes align** (3 points)
  - Checks if PDF content aligns with reported learning outcomes
- **Objectives match** (3 points)
  - Validates PDF content against stated objectives
- **Participant info matches** (5 points)
  - Verifies participant count in PDF matches submission data

### 3. Image Validation (14 points)
- **GeoTag present** (6 points) - Currently disabled
- **Banner/Poster visible** (2 points)
  - Uses AI vision to detect event banners/posters in images
- **Event scene is real activity** (3 points)
  - Validates that images show actual event activities
- **Event mode matches** (5 points)
  - Checks if images match reported online/offline mode
- **20+ participants visible** (4 points)
  - Counts visible participants in images using AI vision

### 4. Duplicate Detection (15 points)
- **Duplicate photo detection** (15 points)
  - Uses perceptual hashing (pHash) to detect duplicate images within batch
  - Prevents same photos being reused across submissions

## Final Status Determination

- **Accepted**: Score ≥ 60 points AND all mandatory files present
- **Rejected**: Score < 60 points OR mandatory files missing
- **Reopen**: Mandatory files (PDF or images) are missing

## Key Features

### 1. AI-Powered Validation
- Uses **Google Gemini 2.5 Pro** for text and vision analysis
- **Groq** as automatic fallback when Gemini is unavailable
- Semantic understanding for theme alignment
- Vision AI for image content analysis

### 2. Rate Limiting & Circuit Breaker
- **Token Bucket Rate Limiter** with jitter to prevent API throttling
- **Circuit Breaker** pattern to prevent API hammering during sustained errors
- Configurable rate limits (148 RPM for Gemini, 20 RPM for Groq)
- Automatic fallback to Groq when circuit breaker opens

### 3. Performance Optimizations
- **Parallel processing** with 12 workers (configurable)
- **Concurrency control** via semaphores (6 concurrent Gemini calls)
- **Heuristic pre-scoring** to identify weak submissions early
- **Request budget tracking** to limit API calls per submission
- **Response caching** to avoid redundant API calls

### 4. Azure Blob Storage Integration
- Downloads PDFs and images from Azure Blob Storage URLs
- Progressive URL probing based on `event_driven` type and academic year
- Automatic cleanup of downloaded files after processing

### 5. Dual Interface
- **CLI Tool**: `python -m event_validator.main` for batch CSV processing
- **REST API**: FastAPI server for programmatic access
  - POST `/validate/batch` - Validate submissions
  - GET `/download/{filename}` - Download results
  - GET `/health` - Health check

### 6. Robust Error Handling
- Exponential backoff for 429 (rate limit) errors
- Automatic retry logic with configurable attempts
- Graceful degradation when APIs fail
- Detailed error logging and reporting

## Technology Stack

- **Python 3.x**
- **FastAPI** - REST API framework
- **Google Gemini API** - Primary AI service (text + vision)
- **Groq API** - Fallback AI service
- **Pandas** - CSV/Excel processing
- **PyPDF2/pdfplumber** - PDF text extraction
- **Pillow** - Image processing and EXIF data
- **imagehash** - Perceptual hashing for duplicate detection
- **ThreadPoolExecutor** - Parallel processing

## Architecture

```
event_validator/
├── api/                    # FastAPI REST API
│   └── app.py             # Main API endpoints
├── config/                 # Configuration
│   └── rules.py           # Validation rules and scoring
├── extractors/             # Data extraction
│   ├── pdf_extractor.py   # PDF text extraction
│   └── image_extractor.py # Image processing
├── orchestration/          # Main processing logic
│   └── runner.py          # Submission processing pipeline
├── validators/             # Validation modules
│   ├── theme_validator.py # Theme alignment checks
│   ├── pdf_validator.py   # PDF content validation
│   ├── image_validator.py # Image content validation
│   ├── duplicate_validator.py # Duplicate detection
│   ├── gemini_client.py   # Gemini API client
│   └── groq_client.py     # Groq API client
└── utils/                  # Utilities
    ├── rate_limiter.py    # Token bucket rate limiter
    ├── circuit_breaker.py  # Circuit breaker pattern
    ├── concurrency.py     # Concurrency control
    ├── request_budget.py  # API call budget tracking
    ├── downloader.py      # Azure Blob Storage downloader
    ├── column_mapper.py   # CSV column mapping
    └── blob_path_resolver.py # Azure URL resolution
```

## Configuration

Configuration is managed via `.env` file:

- **API Keys**: `GEMINI_API_KEY`, `GROQ_API_KEY`
- **Rate Limits**: `GEMINI_RPM_LIMIT=148`, `GROQ_RPM_LIMIT=20`
- **Concurrency**: `GEMINI_MAX_CONCURRENT=6`, `DEFAULT_MAX_WORKERS=12`
- **Circuit Breaker**: Error threshold (70%), window (30s), cooldown (10s)
- **Acceptance Threshold**: `ACCEPTANCE_THRESHOLD=60`
- **Safety Factor**: `RATE_LIMIT_SAFETY_FACTOR=0.98`

## Performance Metrics

- **Target**: Process 100 records in ~8 minutes
- **Throughput**: ~148 requests/minute (Gemini API limit)
- **Concurrency**: 12 parallel workers × 6 concurrent API calls
- **Optimization**: Heuristic pre-scoring saves 30-50% of API calls

## Output

The system generates enriched CSV files with:
- Original submission data
- **Overall Score** (0-100)
- **Status** (Accepted/Rejected/Reopen)
- **Requirements Not Met** (detailed failure reasons)

## Use Cases

1. **Batch Processing**: Process large CSV files (1000s of records) via CLI
2. **API Integration**: Integrate with other systems via REST API
3. **Quality Assurance**: Automatically validate event submissions before approval
4. **Audit Trail**: Detailed logging of all validation decisions

## Security & Compliance

- API keys stored in environment variables (`.env`)
- No hardcoded credentials
- Detailed audit logging for government compliance
- File cleanup after processing
- Error messages designed for audit trails

## Future Enhancements

- Currently disabled validations (Year alignment, GeoTag) can be re-enabled
- Additional validation rules can be added
- Support for more file formats
- Enhanced duplicate detection across historical submissions
- Dashboard for validation statistics

---

**Version**: 2.0.0  
**Status**: Production-ready  
**Maintained by**: Government Data Validation Team
