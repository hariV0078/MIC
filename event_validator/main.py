"""Main entry point for event validation system."""
import argparse
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

from event_validator.utils.logging_config import setup_logging
from event_validator.types import ValidationConfig
from event_validator.orchestration.runner import process_csv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Event Validation System - MVP"
    )
    parser.add_argument(
        'input_csv',
        type=str,
        help='Path to input CSV file'
    )
    parser.add_argument(
        '--output-csv',
        type=str,
        default=None,
        help='Path to output CSV file (default: input_csv with _enriched suffix)'
    )
    parser.add_argument(
        '--base-image-path',
        type=str,
        default=None,
        help='Base directory path for duplicate image detection'
    )
    parser.add_argument(
        '--groq-api-key',
        type=str,
        default=None,
        help='Groq API key (or set GROQ_API_KEY env var)'
    )
    parser.add_argument(
        '--acceptance-threshold',
        type=int,
        default=75,
        help='Acceptance threshold score (default: 75)'
    )
    parser.add_argument(
        '--phash-threshold',
        type=int,
        default=5,
        help='pHash Hamming distance threshold for duplicates (default: 5)'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default=None,
        help='Optional log file path'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(log_level=args.log_level, log_file=log_file)
    
    # Setup configuration
    input_csv = Path(args.input_csv)
    
    if args.output_csv:
        output_csv = Path(args.output_csv)
    else:
        # Default: add _enriched suffix
        stem = input_csv.stem
        output_csv = input_csv.parent / f"{stem}_enriched.csv"
    
    base_image_path = None
    if args.base_image_path:
        base_image_path = Path(args.base_image_path)
    elif os.getenv('BASE_IMAGE_PATH'):
        base_image_path = Path(os.getenv('BASE_IMAGE_PATH'))
    
    # Check for both GROQ_API_KEY and GROQ_CLOUD_API
    groq_api_key = args.groq_api_key or os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
    
    config = ValidationConfig(
        acceptance_threshold=args.acceptance_threshold,
        duplicate_phash_threshold=args.phash_threshold,
        base_image_path=base_image_path,
        groq_api_key=groq_api_key
    )
    
    logger.info("=" * 60)
    logger.info("Event Validation System - MVP")
    logger.info("=" * 60)
    logger.info(f"Input CSV: {input_csv}")
    logger.info(f"Output CSV: {output_csv}")
    logger.info(f"Base Image Path: {base_image_path}")
    logger.info(f"Acceptance Threshold: {config.acceptance_threshold}")
    logger.info(f"Groq API Key: {'Set' if groq_api_key else 'Not set'}")
    logger.info("=" * 60)
    
    # Process CSV
    try:
        process_csv(input_csv, output_csv, config)
        logger.info("Processing completed successfully!")
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()

