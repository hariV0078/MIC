"""FastAPI application for event validation system."""
import logging
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from dotenv import load_dotenv

from event_validator.utils.logging_config import setup_logging
from event_validator.types import ValidationConfig
from event_validator.orchestration.runner import process_submission
from event_validator.validators.gemini_client import GeminiClient
from event_validator.validators.duplicate_validator import reset_batch_hash_tracker

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
    return _gemini_client


def read_file_to_dataframe(file: UploadFile) -> pd.DataFrame:
    """Read CSV or XLSX file to pandas DataFrame."""
    file_extension = Path(file.filename).suffix.lower()
    
    # Read file content
    contents = file.file.read()
    
    if file_extension == '.csv':
        # Try different encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                df = pd.read_csv(io.BytesIO(contents), encoding=encoding)
                return df
            except UnicodeDecodeError:
                continue
        # If all encodings fail, use utf-8 with errors='ignore'
        df = pd.read_csv(io.BytesIO(contents), encoding='utf-8', errors='ignore')
        return df
    
    elif file_extension in ['.xlsx', '.xls']:
        df = pd.read_excel(io.BytesIO(contents))
        return df
    
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {file_extension}. Supported formats: .csv, .xlsx, .xls"
        )


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
            "POST /validate/upload": "Upload CSV/XLSX file for validation",
            "GET /health": "Health check endpoint"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    config = get_config()
    gemini_client = get_gemini_client()
    
    return {
        "status": "healthy",
        "gemini_configured": gemini_client.client is not None,
        "groq_fallback_configured": gemini_client.groq_client is not None and gemini_client.groq_client.client is not None,
        "base_image_path": str(config.base_image_path) if config.base_image_path else None,
        "acceptance_threshold": config.acceptance_threshold
    }


@app.post("/validate/upload")
async def validate_upload(
    file: UploadFile = File(...),
    return_format: str = Query("csv", pattern="^(json|csv|xlsx)$"),  # Default to CSV
    base_image_path: Optional[str] = Query(None, description="Base directory for duplicate detection"),
    gemini_api_key: Optional[str] = Query(None, description="Gemini API key (overrides env var)"),
    acceptance_threshold: Optional[int] = Query(None, description="Acceptance threshold (overrides default 75)")
):
    """
    Upload and validate a CSV or XLSX file.
    
    - **file**: CSV or XLSX file containing event submissions
    - **return_format**: Response format - 'json', 'csv', or 'xlsx'
    - **base_image_path**: Optional base directory for duplicate detection
    - **gemini_api_key**: Optional Gemini API key (overrides environment variable)
    - **acceptance_threshold**: Optional acceptance threshold (overrides default 75)
    """
    try:
        # Read file to DataFrame
        logger.info(f"Processing file: {file.filename}")
        df = read_file_to_dataframe(file)
        
        if df.empty:
            raise HTTPException(status_code=400, detail="File is empty")
        
        # Get configuration
        config = get_config()
        
        # Override config with query parameters if provided
        if base_image_path:
            config.base_image_path = Path(base_image_path)
        if gemini_api_key:
            config.groq_api_key = gemini_api_key  # Using groq_api_key field for backward compatibility
            # Recreate Gemini client with new key and Groq fallback
            global _gemini_client
            groq_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
            _gemini_client = GeminiClient(api_key=gemini_api_key, groq_api_key=groq_key)
        if acceptance_threshold:
            config.acceptance_threshold = acceptance_threshold
        
        gemini_client = get_gemini_client()
        
        # Convert DataFrame to list of dicts
        rows = dataframe_to_dict_list(df)
        
        # Reset batch hash tracker at start of new batch
        reset_batch_hash_tracker()
        
        # Process submissions in parallel for better performance
        max_workers = min(10, len(rows))  # Limit to 10 parallel workers or number of rows, whichever is smaller
        results = []
        
        def process_single_submission(row_data: dict, row_index: int) -> tuple[int, dict]:
            """Process a single submission and return index and result."""
            try:
                logger.info(f"Processing submission {row_index + 1}/{len(rows)}")
                submission = process_submission(row_data, config, gemini_client)
                
                # Create result row (use original row data if available)
                result_row = getattr(submission, '_original_row_data', row_data).copy()
                result_row['Overall Score'] = submission.overall_score
                result_row['Status'] = submission.status
                result_row['Requirements Not Met'] = submission.requirements_not_met
                
                return row_index, result_row
            except Exception as e:
                logger.error(f"Error processing submission {row_index + 1}: {e}", exc_info=True)
                # Add error row
                result_row = row_data.copy()
                result_row['Overall Score'] = 0
                result_row['Status'] = "Error"
                result_row['Requirements Not Met'] = f"Processing error: {str(e)}"
                return row_index, result_row
        
        # Process submissions in parallel using ThreadPoolExecutor
        logger.info(f"Processing {len(rows)} submissions with {max_workers} parallel workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_index = {
                executor.submit(process_single_submission, row, i): i
                for i, row in enumerate(rows)
            }
            
            # Collect results as they complete (maintain order by storing with index)
            indexed_results = {}
            for future in as_completed(future_to_index):
                try:
                    row_index, result_row = future.result()
                    indexed_results[row_index] = result_row
                except Exception as e:
                    original_index = future_to_index[future]
                    logger.error(f"Error processing submission {original_index + 1}: {e}", exc_info=True)
                    error_row = rows[original_index].copy()
                    error_row['Overall Score'] = 0
                    error_row['Status'] = "Error"
                    error_row['Requirements Not Met'] = f"Processing error: {str(e)}"
                    indexed_results[original_index] = error_row
        
        # Reconstruct results in original order
        results = [indexed_results[i] for i in range(len(rows))]
        
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
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
        
        # Process submissions in parallel for better performance
        max_workers = min(10, len(submissions))  # Limit to 10 parallel workers or number of submissions, whichever is smaller
        results = []
        
        def process_single_submission(row_data: dict, row_index: int) -> tuple[int, dict]:
            """Process a single submission and return index and result."""
            try:
                logger.info(f"Processing submission {row_index + 1}/{len(submissions)}")
                submission = process_submission(row_data, config, gemini_client)
                
                # Create result row (use original row data if available)
                result_row = getattr(submission, '_original_row_data', row_data).copy()
                result_row['Overall Score'] = submission.overall_score
                result_row['Status'] = submission.status
                result_row['Requirements Not Met'] = submission.requirements_not_met
                
                return row_index, result_row
            except Exception as e:
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


if __name__ == "__main__":
    import uvicorn
    setup_logging()
    uvicorn.run(app, host="0.0.0.0", port=8000)

