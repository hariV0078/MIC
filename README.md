# Event Validation System - MVP

A production-ready Python system for validating event submissions using hardcoded rules, Gemini AI models, and filesystem-based duplicate detection.

**Available as both CLI tool and FastAPI REST API.**

## Features

- ✅ **Rule-driven validation** with hardcoded scoring rules
- ✅ **Binary scoring** (full points or zero, no partial credit)
- ✅ **Gemini-powered** semantic checks for theme alignment, PDF consistency, and image analysis
- ✅ **Filesystem-based duplicate detection** using SHA256 and perceptual hashing (pHash)
- ✅ **CSV-based workflow** - read from CSV, append results to CSV
- ✅ **DB-free** - no database dependencies
- ✅ **Modular & extensible** architecture

## Project Structure

```
event_validator/
├── api/
│   └── app.py                # FastAPI application
├── config/
│   └── rules.py              # Hardcoded validation rules
├── extractors/
│   ├── pdf_extractor.py      # PDF text extraction
│   └── image_extractor.py    # Image metadata extraction
├── validators/
│   ├── gemini_client.py      # Gemini API client
│   ├── theme_validator.py    # Theme validation
│   ├── pdf_validator.py      # PDF validation
│   ├── image_validator.py    # Image validation
│   └── duplicate_validator.py # Duplicate detection
├── utils/
│   ├── hashing.py            # SHA256 & pHash utilities
│   └── logging_config.py     # Logging setup
├── orchestration/
│   └── runner.py             # Main orchestration logic
├── tests/
│   └── unit/                 # Unit tests
├── types.py                  # Type definitions
├── main.py                   # CLI entry point
└── run_api.py                # FastAPI server runner
```

## Installation

1. **Clone or navigate to the project directory**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   
   **Option A: Using .env file (Recommended)**
   
   Create a `.env` file in the project root:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set your configuration:
   ```env
   GEMINI_API_KEY=your-api-key-here
   BASE_IMAGE_PATH=/path/to/base/images
   ACCEPTANCE_THRESHOLD=75
   PHASH_THRESHOLD=5
   ```
   
   **Option B: Using environment variables**
   ```bash
   export GEMINI_API_KEY="your-api-key-here"
   ```
   
   Or pass it via command line argument (see Usage).

## Usage

### Option 1: FastAPI REST API (Recommended)

See [API_README.md](API_README.md) for detailed API documentation.

**Quick Start:**
```bash
# Start the API server
python run_api.py

# API will be available at http://localhost:8000
# Documentation at http://localhost:8000/docs
```

**Upload and validate a file:**
```bash
curl -X POST "http://localhost:8000/validate/upload?return_format=json" \
  -F "file=@sample_input.csv"
```

### Option 2: CLI Tool

**Basic Usage:**
```bash
python -m event_validator.main input.csv --output-csv output_enriched.csv
```

### With Options

```bash
python -m event_validator.main input.csv \
    --output-csv output_enriched.csv \
    --base-image-path /path/to/base/images \
    --gemini-api-key YOUR_API_KEY \
    --acceptance-threshold 75 \
    --phash-threshold 5 \
    --log-level INFO
```

### Command Line Arguments

- `input_csv` (required): Path to input CSV file
- `--output-csv`: Path to output CSV (default: `{input}_enriched.csv`)
- `--base-image-path`: Base directory for duplicate image detection
- `--gemini-api-key`: Gemini API key (or set `GEMINI_API_KEY` env var)
- `--acceptance-threshold`: Score threshold for acceptance (default: 75)
- `--phash-threshold`: pHash Hamming distance threshold (default: 5)
- `--log-level`: Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
- `--log-file`: Optional log file path

## Input CSV Format

The input CSV should contain the following columns (at minimum):

- `Title`: Event title
- `Objectives`: Event objectives
- `Learning Outcomes`: Learning outcomes
- `Theme`: Event theme
- `Level`: Event level (1, 2, or 3)
- `Duration`: Event duration (e.g., "3h", "2 hours")
- `Participants`: Number of participants
- `Event Date`: Event date
- `Year Type`: Financial or Academic
- `Event Mode`: Online or Offline
- `PDF Path`: Path to PDF file
- `Image Paths`: Comma or semicolon-separated image paths

## Output CSV Format

The output CSV includes all original columns plus:

- `Overall Score`: Total score (0-100)
- `Status`: "Accepted" or "Rejected"
- `Requirements Not Met`: Semicolon-separated list of failed validations

## Validation Rules

### Theme Validation (40 points)
- Title/Objectives/Learning align to theme: **10 points**
- Level matches duration: **11 points**
- Participants reported > 20: **12 points**
- Year alignment (financial vs academic): **7 points**

### PDF Test (25 points)
- PDF title matches metadata: **7 points**
- Expert details present: **7 points**
- Learning outcomes align: **3 points**
- Objectives match: **3 points**
- Participant info matches: **5 points**

### Image Test (20 points)
- GeoTag present: **6 points**
- Banner/Poster visible: **2 points**
- Event scene is real activity: **3 points**
- Event mode matches (online/offline): **5 points**
- 20+ participants visible: **4 points**

### Similarity Test (15 points)
- Duplicate photo detection (filesystem): **15 points**

**Total: 100 points**
**Acceptance Threshold: 75 points**

## Scoring System

- **Binary scoring**: Each rule awards full points or zero (no partial credit)
- **Acceptance**: Score ≥ 75 → "Accepted"
- **Rejection**: Score < 75 → "Rejected"

## Duplicate Detection

The system detects duplicates by:

1. Computing SHA256 hash for each submission image
2. Computing perceptual hash (pHash) for each submission image
3. Scanning the base image directory recursively
4. Comparing hashes:
   - **Exact match**: SHA256 hash matches → duplicate
   - **Similar match**: pHash Hamming distance ≤ threshold → duplicate

## Gemini Integration

Gemini is used for:

1. **Theme semantic alignment**: Checks if title/objectives/learning outcomes align with theme
2. **PDF consistency**: Validates title, objectives, learning outcomes, and participant info
3. **Image analysis**: Detects banners, real events, mode matching, and participant count

All Gemini responses are mapped to binary pass/fail decisions.

## Testing

Run unit tests:

```bash
python -m pytest event_validator/tests/unit/
```

Or run individual test files:

```bash
python -m unittest event_validator.tests.unit.test_rules
python -m unittest event_validator.tests.unit.test_hashing
python -m unittest event_validator.tests.unit.test_score_aggregation
```

## Environment Variables

The system supports environment variables via `.env` file or system environment variables.

### Available Variables

- `GEMINI_API_KEY`: Gemini API key (required for AI validations)
- `BASE_IMAGE_PATH`: Base directory for duplicate detection (optional)
- `ACCEPTANCE_THRESHOLD`: Score threshold for acceptance (default: 75)
- `PHASH_THRESHOLD`: pHash Hamming distance threshold for duplicates (default: 5)

### Using .env File

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your configuration:
   ```env
   GEMINI_API_KEY=your-api-key-here
   BASE_IMAGE_PATH=/path/to/base/images
   ACCEPTANCE_THRESHOLD=75
   PHASH_THRESHOLD=5
   ```

3. The `.env` file is automatically loaded when running the CLI or API.

> **Note:** System environment variables take precedence over `.env` file values.

## Limitations & Future Enhancements

### Current MVP Limitations:
- Image analysis uses text-based prompts (Gemini Vision API not implemented)
- OCR fallback requires additional dependencies
- No concurrent processing (can be added)

### Future Enhancements:
- Gemini Vision API integration for true image analysis
- Concurrent processing for multiple submissions
- Configurable rules (currently hardcoded)
- Additional validation rules
- Performance optimizations

## License

This is an MVP implementation. Modify as needed for your use case.

## Support

For issues or questions, refer to the code documentation or extend the system as needed.

