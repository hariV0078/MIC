"""FastAPI application for event validation system."""
import logging
import io
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from dotenv import load_dotenv

from event_validator.utils.logging_config import setup_logging
from event_validator.types import ValidationConfig
from event_validator.orchestration.runner import process_submission
from event_validator.validators.gemini_client import GeminiClient, set_rate_limit_callback
from event_validator.validators.duplicate_validator import reset_batch_hash_tracker
from event_validator.utils.downloader import (
    start_periodic_cleanup,
    stop_periodic_cleanup,
    cleanup_old_files,
    cleanup_all_files,
    FILE_MAX_AGE
)
from event_validator.utils.file_operations import (
    get_output_file_path,
    list_output_files,
    OUTPUT_DIR
)

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Event Validation System API",
    description="MVP Event Validation System with Google Gemini AI (Parallel Processing) - FastAPI",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global configuration (can be set via environment variables)
_config: Optional[ValidationConfig] = None
_gemini_client: Optional[GeminiClient] = None

# Rate limiting: Use smart rate limiter and dynamic concurrency
# The rate limiter tracks requests per minute and adjusts delays automatically
from event_validator.utils.rate_limiter import get_rate_limiter

# Calculate optimal concurrency based on rate limits
# Gemini-2.5-pro limits: 150 RPM, 2M TPM, 10K RPD
# Using 145 RPM (97% of limit) for maximum throughput
GEMINI_RPM = int(os.getenv('GEMINI_RPM_LIMIT', '145'))

# REDUCED: Workers limited to 4 to prevent burst 429s
# With GEMINI_MAX_CONCURRENT=2 semaphore, this means:
# - Max 4 submissions processing in parallel
# - Max 2 Gemini API calls in flight at once (across all workers)
# This is much more stable than 6 workers with burst
OPTIMAL_CONCURRENCY = min(4, int(os.getenv('DEFAULT_MAX_WORKERS', '4')))  # Default 4, max 4

# Request-level semaphore (legacy, actual concurrency controlled by utils/concurrency.py)
MAX_CONCURRENT_API_CALLS = OPTIMAL_CONCURRENCY * 2
_api_semaphore = threading.Semaphore(MAX_CONCURRENT_API_CALLS)

# Default max workers for parallel processing (reduced from 6 to 4)
DEFAULT_MAX_WORKERS = int(os.getenv('DEFAULT_MAX_WORKERS', '4'))  # Reduced from 6 to 4

# Rate limit detection: Track if we're in rate limit mode (sequential processing)
_rate_limit_detected = threading.Event()


@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup."""
    logger.info("Application startup: Initializing services...")
    
    # Ensure outputs directory exists
    OUTPUT_DIR.mkdir(exist_ok=True)
    logger.info(f"Output directory: {OUTPUT_DIR.absolute()}")
    
    # Start periodic cleanup of downloaded files
    start_periodic_cleanup()
    
    # Perform initial cleanup of old files
    deleted = cleanup_old_files()
    if deleted > 0:
        logger.info(f"Startup cleanup: Deleted {deleted} old file(s)")
    
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup services on application shutdown."""
    logger.info("Application shutdown: Stopping services...")
    
    # Stop periodic cleanup thread
    stop_periodic_cleanup()
    
    logger.info("Application shutdown complete")


def get_config() -> ValidationConfig:
    """Get or create validation configuration."""
    global _config
    if _config is None:
        base_image_path = os.getenv('BASE_IMAGE_PATH')
        # Check for GEMINI_API_KEY, fallback to GROQ_API_KEY for backward compatibility
        gemini_api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GROQ_API_KEY')
        
        _config = ValidationConfig(
            acceptance_threshold=int(os.getenv('ACCEPTANCE_THRESHOLD', '60')),
            duplicate_phash_threshold=int(os.getenv('PHASH_THRESHOLD', '5')),
            base_image_path=Path(base_image_path) if base_image_path else None,
            groq_api_key=gemini_api_key  # Storing Gemini key here for backward compatibility
        )
    return _config


def get_gemini_client() -> GeminiClient:
    """Get or create Gemini client with Groq fallback."""
    global _gemini_client
    if _gemini_client is None:
        config = get_config()
        # Get Gemini API key (from GEMINI_API_KEY or fallback to groq_api_key for backward compatibility)
        gemini_api_key = os.getenv('GEMINI_API_KEY') or config.groq_api_key
        # Get Groq API key for fallback
        groq_api_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
        _gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_api_key)
        
        # Set callback to detect rate limits
        def on_rate_limit_detected():
            """Callback when rate limit is detected in Gemini client."""
            logger.warning("Rate limit detected in Gemini client - switching to sequential mode")
            _rate_limit_detected.set()
        
        set_rate_limit_callback(on_rate_limit_detected)
    return _gemini_client


def dataframe_to_dict_list(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert DataFrame to list of dictionaries."""
    # Replace NaN with empty strings
    df = df.fillna('')
    # Convert to dict records
    return df.to_dict('records')


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Event Validation System API",
        "version": "2.0.0",
        "endpoints": {
            "POST /validate/batch": "Validate batch of submissions from JSON",
            "GET /download/{filename}": "Download generated validation results CSV",
            "GET /downloads": "List all available output files",
            "GET /health": "Health check endpoint"
        },
        "note": "Use CLI tool (python -m event_validator.main) to process CSV files from terminal"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    config = get_config()
    gemini_client = get_gemini_client()
    
    # Check downloaded files directory size
    from event_validator.utils.downloader import DOWNLOAD_DIR
    downloaded_files_count = 0
    downloaded_files_size = 0
    if DOWNLOAD_DIR.exists():
        downloaded_files_count = len(list(DOWNLOAD_DIR.glob("*")))
        downloaded_files_size = sum(f.stat().st_size for f in DOWNLOAD_DIR.glob("*") if f.is_file())
    
    return {
        "status": "healthy",
        "gemini_configured": gemini_client.client is not None,
        "groq_fallback_configured": gemini_client.groq_client is not None and gemini_client.groq_client.client is not None,
        "base_image_path": str(config.base_image_path) if config.base_image_path else None,
        "acceptance_threshold": config.acceptance_threshold,
        "downloaded_files": {
            "count": downloaded_files_count,
            "size_mb": round(downloaded_files_size / (1024 * 1024), 2)
        }
    }


@app.post("/admin/cleanup")
async def manual_cleanup(
    max_age_hours: Optional[int] = Query(None, description="Delete files older than this many hours. If not specified, uses default FILE_MAX_AGE."),
    delete_all: bool = Query(False, description="If true, delete all files regardless of age")
):
    """
    Manually trigger cleanup of downloaded files.
    
    - **max_age_hours**: Delete files older than this many hours
    - **delete_all**: If true, delete all files regardless of age
    """
    try:
        if delete_all:
            deleted = cleanup_all_files()
            return {
                "status": "success",
                "action": "delete_all",
                "files_deleted": deleted,
                "message": f"Deleted {deleted} file(s)"
            }
        else:
            max_age_seconds = max_age_hours * 3600 if max_age_hours else None
            deleted = cleanup_old_files(max_age_seconds)
            return {
                "status": "success",
                "action": "cleanup_old",
                "files_deleted": deleted,
                "max_age_hours": max_age_hours or (FILE_MAX_AGE / 3600),
                "message": f"Deleted {deleted} old file(s)"
            }
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


@app.post("/validate/batch")
async def validate_batch(
    submissions: List[Dict[str, Any]],
    return_format: str = Query("csv", pattern="^(json|csv|xlsx)$"),  # Default to CSV
    base_image_path: Optional[str] = Query(None),
    gemini_api_key: Optional[str] = Query(None),
    acceptance_threshold: Optional[int] = Query(None)
):
    """
    Validate a batch of submissions provided as JSON.
    
    - **submissions**: List of submission dictionaries
    - **base_image_path**: Optional base directory for duplicate detection
    - **gemini_api_key**: Optional Gemini API key
    - **acceptance_threshold**: Optional acceptance threshold
    """
    try:
        # Get configuration
        config = get_config()
        
        # Override config with query parameters if provided
        if base_image_path:
            config.base_image_path = Path(base_image_path)
        if gemini_api_key:
            config.groq_api_key = gemini_api_key  # Using groq_api_key field for backward compatibility
            global _gemini_client
            groq_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
            _gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_key)
        if acceptance_threshold:
            config.acceptance_threshold = acceptance_threshold
        
        gemini_client = get_gemini_client()
        
        # Reset batch hash tracker at start of new batch
        reset_batch_hash_tracker()
        
        # Check if rate limit was detected - if so, use sequential processing
        use_sequential = _rate_limit_detected.is_set()
        
        if use_sequential:
            logger.warning("Rate limit detected - switching to sequential processing mode")
            rate_limiter = get_rate_limiter()
            logger.info(f"Processing {len(submissions)} submissions sequentially (using rate limiter: {rate_limiter.get_current_rate():.1f} RPM)...")
            results = []
            
            for i, row in enumerate(submissions):
                try:
                    logger.info(f"Processing submission {i + 1}/{len(submissions)} (sequential mode)")
                    # Rate limiter will handle delays automatically in gemini_client
                    
                    submission = process_submission(row, config, gemini_client)
                    
                    # Create result row (use original row data if available)
                    result_row = getattr(submission, '_original_row_data', row).copy()
                    result_row['Overall Score'] = submission.overall_score
                    result_row['Status'] = submission.status
                    result_row['Requirements Not Met'] = submission.requirements_not_met
                    results.append(result_row)
                except Exception as e:
                    logger.error(f"Error processing submission {i + 1}: {e}", exc_info=True)
                    # Add error row
                    result_row = row.copy()
                    result_row['Overall Score'] = 0
                    result_row['Status'] = "Error"
                    result_row['Requirements Not Met'] = f"Processing error: {str(e)}"
                    results.append(result_row)
        else:
            # Process submissions in parallel with rate limiting
            # Use smaller number of workers to avoid hitting API rate limits
            max_workers = min(DEFAULT_MAX_WORKERS, len(submissions))
            results = []
            
            def process_single_submission(row_data: dict, row_index: int) -> tuple[int, dict]:
                """Process a single submission with rate limiting and return index and result."""
                # Acquire semaphore to limit concurrent API calls
                # Note: The rate limiter in gemini_client will handle actual API rate limiting
                with _api_semaphore:
                    try:
                        logger.info(f"Processing submission {row_index + 1}/{len(submissions)}")
                        # No fixed delay - rate limiter handles timing automatically
                        submission = process_submission(row_data, config, gemini_client)
                        
                        # Create result row (use original row data if available)
                        result_row = getattr(submission, '_original_row_data', row_data).copy()
                        result_row['Overall Score'] = submission.overall_score
                        result_row['Status'] = submission.status
                        result_row['Requirements Not Met'] = submission.requirements_not_met
                        
                        return row_index, result_row
                    except Exception as e:
                        # Check if it's a rate limit error
                        error_str = str(e).lower()
                        if '429' in error_str or 'rate limit' in error_str or 'quota' in error_str:
                            logger.error(f"Rate limit detected during processing - will switch to sequential mode")
                            _rate_limit_detected.set()
                        
                        logger.error(f"Error processing submission {row_index + 1}: {e}", exc_info=True)
                        # Add error row
                        result_row = row_data.copy()
                        result_row['Overall Score'] = 0
                        result_row['Status'] = "Error"
                        result_row['Requirements Not Met'] = f"Processing error: {str(e)}"
                        return row_index, result_row
            
            # Process submissions in parallel using ThreadPoolExecutor
            logger.info(f"Processing {len(submissions)} submissions with {max_workers} parallel workers...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_index = {
                    executor.submit(process_single_submission, row, i): i
                    for i, row in enumerate(submissions)
                }
                
                # Collect results as they complete (maintain order by storing with index)
                indexed_results = {}
                for future in as_completed(future_to_index):
                    try:
                        row_index, result_row = future.result()
                        indexed_results[row_index] = result_row
                    except Exception as e:
                        original_index = future_to_index[future]
                        # Check if it's a rate limit error
                        error_str = str(e).lower()
                        if '429' in error_str or 'rate limit' in error_str or 'quota' in error_str:
                            logger.error(f"Rate limit detected - will switch to sequential mode")
                            _rate_limit_detected.set()
                        
                        logger.error(f"Error processing submission {original_index + 1}: {e}", exc_info=True)
                        error_row = submissions[original_index].copy()
                        error_row['Overall Score'] = 0
                        error_row['Status'] = "Error"
                        error_row['Requirements Not Met'] = f"Processing error: {str(e)}"
                        indexed_results[original_index] = error_row
                
                # Reconstruct results in original order
                results = [indexed_results[i] for i in range(len(submissions))]
        
        # Convert results to DataFrame
        results_df = pd.DataFrame(results)
        
        # Ensure all required fields are present and properly formatted
        if 'Overall Score' not in results_df.columns:
            results_df['Overall Score'] = 0
        if 'Status' not in results_df.columns:
            results_df['Status'] = 'Error'
        if 'Requirements Not Met' not in results_df.columns:
            results_df['Requirements Not Met'] = ''
        
        # Convert Overall Score to integer for consistency
        results_df['Overall Score'] = pd.to_numeric(results_df['Overall Score'], errors='coerce').fillna(0).astype(int)
        
        # Return based on format
        if return_format == "json":
            return JSONResponse(content=results_df.to_dict('records'))
        
        elif return_format == "csv":
            # Create CSV as bytes with proper encoding for file download
            # Generate CSV content and encode with UTF-8-sig (includes BOM for Excel compatibility)
            csv_content = results_df.to_csv(index=False)
            csv_bytes = csv_content.encode('utf-8-sig')
            
            # Create a generator function for StreamingResponse (required for file downloads)
            def generate_csv():
                yield csv_bytes
            
            return StreamingResponse(
                generate_csv(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="validation_results.csv"',
                    "Content-Type": "text/csv; charset=utf-8",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
        
        elif return_format == "xlsx":
            # Create XLSX in memory
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                results_df.to_excel(writer, index=False, sheet_name='Validation Results')
            output.seek(0)
            
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=validation_results.xlsx"}
            )
    
    except Exception as e:
        logger.error(f"Error processing batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/download/{filename}")
async def download_file(filename: str):
    """
    Download a generated validation results CSV file.
    
    - **filename**: Name of the output file to download (must be a CSV file in outputs directory)
    
    Returns:
        File download response with the CSV file
    """
    try:
        output_path = get_output_file_path(filename)
        
        if output_path is None:
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {filename}. Use /downloads to list available files."
            )
        
        return FileResponse(
            path=output_path,
            media_type="text/csv",
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")


@app.get("/downloads")
async def list_downloads():
    """
    List all available output CSV files in the outputs directory.
    
    Returns:
        JSON response with list of available output files
    """
    try:
        files = list_output_files()
        
        # Get file details (size, modification time)
        file_details = []
        for filename in files:
            file_path = OUTPUT_DIR / filename
            if file_path.exists():
                stat = file_path.stat()
                file_details.append({
                    "filename": filename,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "download_url": f"/download/{filename}"
                })
        
        return JSONResponse(content={
            "status": "success",
            "output_directory": str(OUTPUT_DIR.absolute()),
            "file_count": len(file_details),
            "files": file_details
        })
    
    except Exception as e:
        logger.error(f"Error listing downloads: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    setup_logging()
    uvicorn.run(app, host="0.0.0.0", port=8000)

