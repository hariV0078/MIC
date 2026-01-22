"""Main entry point for event validation system."""
import argparse
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from event_validator.utils.logging_config import setup_logging
from event_validator.types import ValidationConfig
from event_validator.orchestration.runner import process_csv
from event_validator.validators.gemini_client import GeminiClient

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal output."""
    # Reset
    RESET = '\033[0m'
    
    # Text colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    
    # Styles
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'

# Check if colors are supported (Windows needs special handling)
def supports_color():
    """Check if terminal supports colors."""
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Enable ANSI escape sequences on Windows 10+
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except:
            return False
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

# Disable colors if not supported
if not supports_color():
    for attr in dir(Colors):
        if not attr.startswith('_'):
            setattr(Colors, attr, '')


def print_header(text: str, char: str = "=", color: str = Colors.CYAN):
    """Print a formatted header."""
    width = 70
    print()
    print(color + Colors.BOLD + char * width + Colors.RESET)
    print(color + Colors.BOLD + text.center(width) + Colors.RESET)
    print(color + Colors.BOLD + char * width + Colors.RESET)
    print()


def print_success(text: str):
    """Print success message."""
    print(Colors.GREEN + Colors.BOLD + "✓ " + Colors.RESET + Colors.GREEN + text + Colors.RESET)


def print_error(text: str):
    """Print error message."""
    print(Colors.RED + Colors.BOLD + "✗ " + Colors.RESET + Colors.RED + text + Colors.RESET)


def print_warning(text: str):
    """Print warning message."""
    print(Colors.YELLOW + Colors.BOLD + "⚠ " + Colors.RESET + Colors.YELLOW + text + Colors.RESET)


def print_info(text: str):
    """Print info message."""
    print(Colors.CYAN + "ℹ " + Colors.RESET + Colors.BRIGHT_CYAN + text + Colors.RESET)


def print_section(text: str):
    """Print section header."""
    print()
    print(Colors.BRIGHT_BLUE + Colors.BOLD + "▶ " + text + Colors.RESET)
    print(Colors.DIM + "─" * 70 + Colors.RESET)


def print_banner():
    """Print application banner."""
    banner = """
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║          Event Validation System - AI Powered                ║
    ║                                                               ║
    ║          Powered by Google Gemini & Groq                     ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """
    print(Colors.CYAN + Colors.BOLD + banner + Colors.RESET)


def prompt_input(prompt_text: str, default: str = None, file_type: str = None) -> str:
    """Prompt user for input in terminal with enhanced formatting."""
    if default:
        prompt = (
            Colors.CYAN + Colors.BOLD + "? " + Colors.RESET + 
            Colors.BRIGHT_WHITE + prompt_text + Colors.RESET + 
            Colors.DIM + f" (default: {default})" + Colors.RESET + 
            Colors.CYAN + ": " + Colors.RESET
        )
    else:
        prompt = (
            Colors.CYAN + Colors.BOLD + "? " + Colors.RESET + 
            Colors.BRIGHT_WHITE + prompt_text + Colors.RESET + 
            Colors.CYAN + ": " + Colors.RESET
        )
    
    user_input = input(prompt).strip()
    
    if not user_input and default:
        print(Colors.DIM + f"Using default: {default}" + Colors.RESET)
        return default
    
    if not user_input:
        print_error("This field is required. Please try again.")
        return prompt_input(prompt_text, default, file_type)
    
    # Validate file path if file_type is specified
    if file_type == "file":
        path = Path(user_input)
        if not path.exists():
            print_error(f"File not found: {user_input}")
            print_info("Please check the path and try again.")
            return prompt_input(prompt_text, default, file_type)
        if not path.is_file():
            print_error(f"Path is not a file: {user_input}")
            return prompt_input(prompt_text, default, file_type)
        print_success(f"File found: {user_input}")
    
    return user_input


def main():
    """Main entry point with interactive prompts."""
    parser = argparse.ArgumentParser(
        description="Event Validation System - MVP (Interactive Mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --non-interactive input.csv
  python main.py --non-interactive input.csv --output-csv output.csv
        """
    )
    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help='Run in non-interactive mode (use command-line arguments)'
    )
    parser.add_argument(
        'input_csv',
        type=str,
        nargs='?',
        help='Path to input CSV file (required in non-interactive mode)'
    )
    parser.add_argument(
        '--output-csv',
        type=str,
        default=None,
        help='Path to output CSV file (default: auto-generated in ./outputs/)'
    )
    parser.add_argument(
        '--base-image-path',
        type=str,
        default=None,
        help='Base directory path for duplicate image detection'
    )
    parser.add_argument(
        '--gemini-api-key',
        type=str,
        default=None,
        help='Gemini API key (or set GEMINI_API_KEY env var)'
    )
    parser.add_argument(
        '--groq-api-key',
        type=str,
        default=None,
        help='Groq API key for fallback (or set GROQ_API_KEY env var)'
    )
    parser.add_argument(
        '--acceptance-threshold',
        type=int,
        default=60,
        help='Acceptance threshold score (default: 60)'
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
    
    # Interactive mode: prompt for input file path
    if not args.non_interactive:
        print_banner()
        print()
        
        print_section("Configuration")
        
        # Prompt for input file path
        input_csv_str = prompt_input("Enter the input CSV file path", file_type="file")
        input_csv = Path(input_csv_str)
        
        # Use default output location (./outputs/)
        from datetime import datetime
        from event_validator.utils.file_operations import OUTPUT_DIR, generate_output_filename
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_filename = generate_output_filename(str(input_csv))
        output_csv = OUTPUT_DIR / output_filename
        
        # Use environment variables or defaults for other settings
        base_image_path = None
        if os.getenv('BASE_IMAGE_PATH'):
            base_image_path = Path(os.getenv('BASE_IMAGE_PATH'))
        
        gemini_api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GROQ_API_KEY')
        groq_api_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
        acceptance_threshold = int(os.getenv('ACCEPTANCE_THRESHOLD', '60'))
        phash_threshold = int(os.getenv('PHASH_THRESHOLD', '5'))
        
        print_section("Processing Summary")
        print(Colors.BRIGHT_WHITE + "  Input File:  " + Colors.RESET + str(input_csv))
        print(Colors.BRIGHT_WHITE + "  Output File: " + Colors.RESET + str(output_csv))
        print(Colors.BRIGHT_WHITE + "  Threshold:   " + Colors.RESET + f"{acceptance_threshold} points")
        if gemini_api_key:
            print(Colors.BRIGHT_WHITE + "  API Status:  " + Colors.RESET + Colors.GREEN + "✓ Gemini API configured" + Colors.RESET)
        else:
            print(Colors.BRIGHT_WHITE + "  API Status:  " + Colors.RESET + Colors.RED + "✗ No API key found" + Colors.RESET)
        
        print()
        print(Colors.BRIGHT_YELLOW + Colors.BOLD + "Starting validation process..." + Colors.RESET)
        print(Colors.DIM + "─" * 70 + Colors.RESET)
        print()
    
    else:
        # Non-interactive mode: use command-line arguments
        if not args.input_csv:
            parser.error("input_csv is required in non-interactive mode")
        
        input_csv = Path(args.input_csv)
        
        if not input_csv.exists():
            print_error(f"File not found: {input_csv}")
            logger.error(f"File not found: {input_csv}")
            return 1
        
        if args.output_csv:
            output_csv = Path(args.output_csv)
        else:
            # Default: save to ./outputs/ directory with timestamp
            from datetime import datetime
            from event_validator.utils.file_operations import OUTPUT_DIR, generate_output_filename
            OUTPUT_DIR.mkdir(exist_ok=True)
            output_filename = generate_output_filename(str(input_csv))
            output_csv = OUTPUT_DIR / output_filename
        
        base_image_path = None
        if args.base_image_path:
            base_image_path = Path(args.base_image_path)
        elif os.getenv('BASE_IMAGE_PATH'):
            base_image_path = Path(os.getenv('BASE_IMAGE_PATH'))
        
        gemini_api_key = args.gemini_api_key or os.getenv('GEMINI_API_KEY') or os.getenv('GROQ_API_KEY')
        groq_api_key = args.groq_api_key or os.getenv('GROQ_API_KEY') or os.getenv('GROQ_CLOUD_API')
        acceptance_threshold = args.acceptance_threshold
        phash_threshold = args.phash_threshold
        
        # Print brief info in non-interactive mode
        print_info(f"Processing: {input_csv.name}")
        print_info(f"Output: {output_csv.name}")
    
    # Create configuration
    config = ValidationConfig(
        acceptance_threshold=acceptance_threshold,
        duplicate_phash_threshold=phash_threshold,
        base_image_path=base_image_path,
        groq_api_key=gemini_api_key  # Storing Gemini key here for backward compatibility
    )
    
    logger.info("=" * 60)
    logger.info("Event Validation System - MVP")
    logger.info("=" * 60)
    logger.info(f"Input CSV: {input_csv}")
    logger.info(f"Output CSV: {output_csv}")
    logger.info(f"Base Image Path: {base_image_path}")
    logger.info(f"Acceptance Threshold: {config.acceptance_threshold}")
    logger.info(f"Gemini API Key: {'Set' if gemini_api_key else 'Not set'}")
    logger.info(f"Groq API Key (fallback): {'Set' if groq_api_key else 'Not set'}")
    logger.info("=" * 60)
    
    # Process CSV
    try:
        process_csv(input_csv, output_csv, config, gemini_api_key=gemini_api_key, groq_api_key=groq_api_key)
        logger.info("=" * 60)
        logger.info("Processing completed successfully!")
        logger.info(f"Output saved to: {output_csv}")
        logger.info("=" * 60)
        
        if not args.non_interactive:
            # Read output CSV to show statistics
            import csv
            try:
                with open(output_csv, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    
                    if rows:
                        total = len(rows)
                        accepted = sum(1 for r in rows if r.get('Status', '').upper() == 'ACCEPTED')
                        rejected = sum(1 for r in rows if r.get('Status', '').upper() == 'REJECTED')
                        reopen = sum(1 for r in rows if r.get('Status', '').upper() == 'REOPEN')
                        error = sum(1 for r in rows if r.get('Status', '').upper() == 'ERROR')
                        
                        # Calculate average score
                        scores = []
                        for r in rows:
                            try:
                                score = int(float(r.get('Overall Score', 0)))
                                scores.append(score)
                            except (ValueError, TypeError):
                                pass
                        avg_score = sum(scores) / len(scores) if scores else 0
                        
                        print()
                        print_header("Processing Complete", "=", Colors.GREEN)
                        print_success("All submissions processed successfully!")
                        print()
                        print_section("Summary Statistics")
                        print(Colors.BRIGHT_WHITE + f"  Total Submissions:  " + Colors.RESET + Colors.BOLD + str(total) + Colors.RESET)
                        print(Colors.GREEN + f"  ✓ Accepted:        " + Colors.RESET + Colors.BRIGHT_GREEN + str(accepted) + Colors.RESET)
                        print(Colors.RED + f"  ✗ Rejected:        " + Colors.RESET + Colors.BRIGHT_RED + str(rejected) + Colors.RESET)
                        print(Colors.YELLOW + f"  ⚠ Reopen:          " + Colors.RESET + Colors.BRIGHT_YELLOW + str(reopen) + Colors.RESET)
                        if error > 0:
                            print(Colors.RED + f"  ✗ Errors:          " + Colors.RESET + Colors.BRIGHT_RED + str(error) + Colors.RESET)
                        if scores:
                            print(Colors.CYAN + f"  📊 Avg Score:      " + Colors.RESET + Colors.BRIGHT_CYAN + f"{avg_score:.1f}/100" + Colors.RESET)
                        print()
                        print_section("Output File")
                        print(Colors.BRIGHT_WHITE + "  File:     " + Colors.RESET + Colors.BRIGHT_CYAN + str(output_csv.name) + Colors.RESET)
                        print(Colors.BRIGHT_WHITE + "  Location: " + Colors.RESET + Colors.DIM + str(output_csv.absolute()) + Colors.RESET)
                        print()
                        print(Colors.GREEN + Colors.BOLD + "✓ Validation complete! Check the output file for detailed results." + Colors.RESET)
                        print()
            except Exception as e:
                # If we can't read the file, just show basic success message
                print()
                print_header("Processing Complete", "=", Colors.GREEN)
                print_success("All submissions processed successfully!")
                print()
                print_section("Results")
                print(Colors.BRIGHT_WHITE + "  Output File: " + Colors.RESET + Colors.BRIGHT_CYAN + str(output_csv) + Colors.RESET)
                print(Colors.BRIGHT_WHITE + "  Location:    " + Colors.RESET + Colors.DIM + str(output_csv.absolute()) + Colors.RESET)
                print()
                print(Colors.GREEN + Colors.BOLD + "✓ Validation complete! Check the output file for detailed results." + Colors.RESET)
                print()
        
        return 0
    except KeyboardInterrupt:
        print()
        print_error("Processing interrupted by user")
        if not args.non_interactive:
            print_warning("Partial results may be available in the output file.")
        return 130
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        if not args.non_interactive:
            print()
            print_header("Processing Failed", "=", Colors.RED)
            print_error(f"An error occurred during processing: {str(e)}")
            print()
            print_info("Check the logs for more details.")
            print()
        raise


if __name__ == '__main__':
    main()

