# Event Validation System - FastAPI

FastAPI-based REST API for the Event Validation System.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

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
export BASE_IMAGE_PATH="/path/to/base/images"  # Optional
export ACCEPTANCE_THRESHOLD=75  # Optional, default is 75
export PHASH_THRESHOLD=5  # Optional, default is 5
```

> **Note:** The `.env` file is automatically loaded when using the API or CLI. Environment variables set in the shell take precedence over `.env` file values.

### 3. Run the API Server

```bash
python run_api.py
```

Or using uvicorn directly:

```bash
uvicorn event_validator.api.app:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at: `http://localhost:8000`

### 4. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### 1. Root Endpoint

**GET** `/`

Returns API information and available endpoints.

**Response:**
```json
{
  "message": "Event Validation System API",
  "version": "1.0.0",
  "endpoints": {
    "POST /validate/upload": "Upload CSV/XLSX file for validation",
    "GET /health": "Health check endpoint"
  }
}
```

### 2. Health Check

**GET** `/health`

Check API health and configuration status.

**Response:**
```json
{
  "status": "healthy",
  "gemini_configured": true,
  "base_image_path": "/path/to/images",
  "acceptance_threshold": 75
}
```

### 3. Validate Upload (File Upload)

**POST** `/validate/upload`

Upload a CSV or XLSX file for validation.

**Parameters:**
- `file` (form-data, required): CSV or XLSX file
- `return_format` (query, optional): Response format - `json`, `csv`, or `xlsx` (default: `json`)
- `base_image_path` (query, optional): Base directory for duplicate detection
- `gemini_api_key` (query, optional): Gemini API key (overrides env var)
- `acceptance_threshold` (query, optional): Acceptance threshold (overrides default 75)

**Example using curl:**

```bash
# JSON response
curl -X POST "http://localhost:8000/validate/upload?return_format=json" \
  -F "file=@sample_input.csv"

# CSV response
curl -X POST "http://localhost:8000/validate/upload?return_format=csv" \
  -F "file=@sample_input.csv" \
  -o results.csv

# XLSX response
curl -X POST "http://localhost:8000/validate/upload?return_format=xlsx" \
  -F "file=@sample_input.xlsx" \
  -o results.xlsx
```

**Example using Python requests:**

```python
import requests

url = "http://localhost:8000/validate/upload"
files = {"file": open("sample_input.csv", "rb")}
params = {"return_format": "json"}

response = requests.post(url, files=files, params=params)
results = response.json()
print(results)
```

**Response (JSON format):**
```json
[
  {
    "Title": "Workshop on AI Ethics",
    "Objectives": "To understand ethical implications of AI",
    "Overall Score": 85,
    "Status": "Accepted",
    "Requirements Not Met": ""
  },
  {
    "Title": "Data Science Bootcamp",
    "Objectives": "Introduction to data science",
    "Overall Score": 60,
    "Status": "Rejected",
    "Requirements Not Met": "Level Validation: Duration 6h maps to Level 3, but Level 2 selected; Participants reported: 15 (needs > 20)"
  }
]
```

### 4. Validate Batch (JSON)

**POST** `/validate/batch`

Validate a batch of submissions provided as JSON.

**Request Body:**
```json
[
  {
    "Title": "Workshop on AI Ethics",
    "Objectives": "To understand ethical implications of AI",
    "Learning Outcomes": "Participants will learn about AI ethics frameworks",
    "Theme": "AI Ethics",
    "Level": "2",
    "Duration": "3h",
    "Participants": "25",
    "Event Date": "2024-03-15",
    "Year Type": "Financial",
    "Event Mode": "Offline",
    "PDF Path": "/path/to/sample.pdf",
    "Image Paths": "/path/to/image1.jpg,/path/to/image2.jpg"
  }
]
```

**Query Parameters:**
- `base_image_path` (optional): Base directory for duplicate detection
- `gemini_api_key` (optional): Gemini API key
- `acceptance_threshold` (optional): Acceptance threshold

**Example:**

```python
import requests

url = "http://localhost:8000/validate/batch"
data = [
    {
        "Title": "Workshop on AI Ethics",
        "Objectives": "To understand ethical implications of AI",
        "Learning Outcomes": "Participants will learn about AI ethics frameworks",
        "Theme": "AI Ethics",
        "Level": "2",
        "Duration": "3h",
        "Participants": "25",
        "Event Date": "2024-03-15",
        "Year Type": "Financial",
        "Event Mode": "Offline",
        "PDF Path": "/path/to/sample.pdf",
        "Image Paths": "/path/to/image1.jpg"
    }
]

response = requests.post(url, json=data)
results = response.json()
print(results)
```

## Input File Format

The CSV or XLSX file should contain the following columns:

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
- `PDF Path`: Path to PDF file (absolute or relative to server)
- `Image Paths`: Comma or semicolon-separated image paths

## Output Format

The response includes all original columns plus:

- `Overall Score`: Total score (0-100)
- `Status`: "Accepted" or "Rejected"
- `Requirements Not Met`: Semicolon-separated list of failed validations

## Error Handling

The API returns appropriate HTTP status codes:

- `200 OK`: Successful validation
- `400 Bad Request`: Invalid file format or empty file
- `500 Internal Server Error`: Processing error

Errors in individual submissions are captured in the `Status` field as "Error" with details in `Requirements Not Met`.

## CORS Configuration

The API includes CORS middleware configured to allow all origins. For production, update the CORS settings in `event_validator/api/app.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

## Production Deployment

### Using Gunicorn with Uvicorn Workers

```bash
pip install gunicorn
gunicorn event_validator.api.app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Using Docker

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY event_validator/ ./event_validator/
COPY run_api.py .

ENV GEMINI_API_KEY=""
ENV BASE_IMAGE_PATH=""

EXPOSE 8000

CMD ["python", "run_api.py"]
```

Build and run:

```bash
docker build -t event-validator-api .
docker run -p 8000:8000 -e GEMINI_API_KEY="your-key" event-validator-api
```

## Testing the API

### Using Swagger UI

1. Navigate to http://localhost:8000/docs
2. Click on `/validate/upload`
3. Click "Try it out"
4. Upload a file
5. Click "Execute"

### Using curl

```bash
# Health check
curl http://localhost:8000/health

# Upload and validate
curl -X POST "http://localhost:8000/validate/upload?return_format=json" \
  -F "file=@sample_input.csv"
```

### Using Python

```python
import requests

# Health check
response = requests.get("http://localhost:8000/health")
print(response.json())

# Upload file
with open("sample_input.csv", "rb") as f:
    files = {"file": f}
    response = requests.post(
        "http://localhost:8000/validate/upload",
        files=files,
        params={"return_format": "json"}
    )
    print(response.json())
```

## Notes

- File paths in CSV/XLSX should be absolute paths or relative to the server's working directory
- Large files may take time to process - consider implementing async processing for production
- Gemini API calls are rate-limited - consider implementing rate limiting and retry logic
- For production, add authentication and authorization
- Consider adding request size limits for file uploads

