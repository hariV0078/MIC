"""File operations utilities for reading and writing CSV files."""
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

# Output directory for generated CSV files
OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


def read_csv_from_path(file_path: str) -> pd.DataFrame:
    """
    Read CSV or XLSX file from filesystem path.
    
    Args:
        file_path: Path to the CSV/XLSX file on the server filesystem
        
    Returns:
        pandas DataFrame containing the file data
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If the file format is unsupported or file is empty
        Exception: For other file reading errors
    """
    path = Path(file_path)
    
    # Validate file exists
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    
    # Get file extension
    file_extension = path.suffix.lower()
    
    try:
        if file_extension == '.csv':
            # Try different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    df = pd.read_csv(path, encoding=encoding)
                    if df.empty:
                        raise ValueError(f"CSV file is empty: {file_path}")
                    return df
                except UnicodeDecodeError:
                    continue
            # If all encodings fail, use utf-8 with errors='ignore'
            df = pd.read_csv(path, encoding='utf-8', errors='ignore')
            if df.empty:
                raise ValueError(f"CSV file is empty: {file_path}")
            return df
        
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(path)
            if df.empty:
                raise ValueError(f"Excel file is empty: {file_path}")
            return df
        
        else:
            raise ValueError(
                f"Unsupported file format: {file_extension}. "
                f"Supported formats: .csv, .xlsx, .xls"
            )
    
    except pd.errors.EmptyDataError:
        raise ValueError(f"File is empty or has no data: {file_path}")
    except pd.errors.ParserError as e:
        raise ValueError(f"Invalid CSV format: {str(e)}")
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}", exc_info=True)
        raise Exception(f"Failed to read file: {str(e)}")


def generate_output_filename(input_path: Optional[str] = None) -> str:
    """
    Generate a unique output filename based on timestamp and optional input filename.
    
    Args:
        input_path: Optional input file path to extract base name from
        
    Returns:
        Generated filename string (e.g., "validation_results_20250122_143022.csv")
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if input_path:
        # Extract base name from input path
        input_name = Path(input_path).stem
        # Sanitize filename (remove special characters)
        safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in input_name)
        filename = f"validation_results_{safe_name}_{timestamp}.csv"
    else:
        filename = f"validation_results_{timestamp}.csv"
    
    return filename


def save_results_to_csv(results_df: pd.DataFrame, filename: Optional[str] = None) -> Path:
    """
    Save validation results DataFrame to CSV file in outputs directory.
    
    Args:
        results_df: DataFrame containing validation results
        filename: Optional custom filename. If not provided, generates one automatically.
        
    Returns:
        Path to the saved output file
        
    Raises:
        Exception: If file saving fails
    """
    try:
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(exist_ok=True)
        
        # Generate filename if not provided
        if not filename:
            filename = generate_output_filename()
        
        # Ensure .csv extension
        if not filename.endswith('.csv'):
            filename = f"{filename}.csv"
        
        # Full output path
        output_path = OUTPUT_DIR / filename
        
        # Save DataFrame to CSV with UTF-8-sig encoding (BOM for Excel compatibility)
        results_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        logger.info(f"Results saved to: {output_path}")
        return output_path
    
    except Exception as e:
        logger.error(f"Error saving results to CSV: {e}", exc_info=True)
        raise Exception(f"Failed to save output file: {str(e)}")


def get_output_file_path(filename: str) -> Optional[Path]:
    """
    Get the full path to an output file if it exists.
    
    Args:
        filename: Name of the output file
        
    Returns:
        Path object if file exists, None otherwise
    """
    # Sanitize filename to prevent directory traversal
    safe_filename = Path(filename).name
    output_path = OUTPUT_DIR / safe_filename
    
    if output_path.exists() and output_path.is_file():
        return output_path
    
    return None


def list_output_files() -> list[str]:
    """
    List all output CSV files in the outputs directory.
    
    Returns:
        List of output filenames
    """
    if not OUTPUT_DIR.exists():
        return []
    
    return [
        f.name for f in OUTPUT_DIR.glob("*.csv")
        if f.is_file()
    ]
