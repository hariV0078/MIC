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
    "POST /validate/file": "Process CSV/XLSX file from server filesystem",
    "POST /validate/batch": "Validate batch of submissions from JSON",
    "GET /download/{filename}": "Download generated validation results CSV",
    "GET /downloads": "List all available output files",
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

### 3. Validate File (Process CSV from Server Filesystem)

**POST** `/validate/file`

Process and validate a CSV or XLSX file that exists on the server filesystem. The file is read from the server, processed, and results are automatically saved to the `./outputs/` directory.

**Parameters:**
- `file_path` (query, required): Path to CSV/XLSX file on server filesystem
- `base_image_path` (query, optional): Base directory for duplicate detection
- `gemini_api_key` (query, optional): Gemini API key (overrides env var)
- `acceptance_threshold` (query, optional): Acceptance threshold (overrides default 60)

**Example using curl:**

```bash
# Process file and get output file information
curl -X POST "http://localhost:8000/validate/file?file_path=/path/to/sample_input.csv"
```

**Example using Python requests:**

```python
import requests

url = "http://localhost:8000/validate/file"
params = {
    "file_path": "/path/to/sample_input.csv",
    "acceptance_threshold": 60
}

response = requests.post(url, params=params)
result = response.json()
print(f"Output file: {result['output_file']}")
print(f"Download URL: {result['download_url']}")
```

**Response:**
```json
{
  "status": "success",
  "message": "Processed 10 submissions successfully",
  "input_file": "/path/to/sample_input.csv",
  "output_file": "validation_results_sample_input_20250122_143022.csv",
  "output_path": "./outputs/validation_results_sample_input_20250122_143022.csv",
  "download_url": "/download/validation_results_sample_input_20250122_143022.csv",
  "summary": {
    "total_submissions": 10,
    "accepted": 7,
    "rejected": 2,
    "reopen": 1,
    "errors": 0
  }
}
```

**Error Responses:**

- **404 File Not Found:**
```json
{
  "detail": "File not found: /path/to/nonexistent.csv"
}
```

- **400 Invalid File Format:**
```json
{
  "detail": "Unsupported file format: .txt. Supported formats: .csv, .xlsx, .xls"
}
```

- **400 Empty File:**
```json
{
  "detail": "CSV file is empty: /path/to/empty.csv"
}
```

### 4. Download Results File

**GET** `/download/{filename}`

Download a generated validation results CSV file from the outputs directory.

**Parameters:**
- `filename` (path, required): Name of the output CSV file to download

**Example using curl:**

```bash
curl -X GET "http://localhost:8000/download/validation_results_sample_input_20250122_143022.csv" \
  -o results.csv
```

**Example using Python requests:**

```python
import requests

url = "http://localhost:8000/download/validation_results_sample_input_20250122_143022.csv"
response = requests.get(url)

with open("results.csv", "wb") as f:
    f.write(response.content)
```

**Error Response (404):**
```json
{
  "detail": "File not found: invalid_filename.csv. Use /downloads to list available files."
}
```

### 5. List Available Downloads

**GET** `/downloads`

List all available output CSV files in the outputs directory.

**Response:**
```json
{
  "status": "success",
  "output_directory": "/opt/MIC/outputs",
  "file_count": 3,
  "files": [
    {
      "filename": "validation_results_sample_input_20250122_143022.csv",
      "size_bytes": 15234,
      "size_mb": 0.01,
      "modified": "2025-01-22T14:30:22",
      "download_url": "/download/validation_results_sample_input_20250122_143022.csv"
    }
  ]
}
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

- `200 OK`: Successful validation or file download
- `400 Bad Request`: Invalid file format, empty file, or invalid CSV format
- `404 Not Found`: File not found (input file or output file for download)
- `500 Internal Server Error`: Processing error or file I/O error

Errors in individual submissions are captured in the `Status` field as "Error" with details in `Requirements Not Met`.

### Common Error Scenarios

1. **File Not Found (404)**: The input file path doesn't exist on the server
2. **Invalid File Format (400)**: File extension is not .csv, .xlsx, or .xls
3. **Empty File (400)**: The CSV/Excel file has no data rows
4. **Invalid CSV Format (400)**: The CSV file cannot be parsed (malformed)
5. **Processing Error (500)**: An error occurred during validation processing

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

