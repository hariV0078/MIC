# test_runner.py
import argparse
import pandas as pd
import sys
import os
from pathlib import Path
import httpx

# --- START PERMANENT FIX ---
# Resolve the project root dynamically and add it to the Python path.
try:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from event_validator_ollama.event_validator.validators.ollama_client import OllamaClient
    from event_validator_ollama.event_validator.extractors.pdf_extractor import extract_pdf_data_from_bytes
except ImportError:
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root.parent))
    from event_validator_ollama.event_validator.validators.ollama_client import OllamaClient
    from event_validator_ollama.event_validator.extractors.pdf_extractor import extract_pdf_data_from_bytes
# --- END PERMANENT FIX ---

# ANSI color codes for terminal output
class Colors:
    RESET, GREEN, RED, YELLOW, CYAN, BOLD = '\033[0m', '\033[32m', '\033[31m', '\033[93m', '\033[96m', '\033[1m'

def print_color(text, color):
    print(f"{color}{text}{Colors.RESET}")

def get_base_url(event_driven):
    try: event_driven = int(event_driven)
    except: return None
    if event_driven in [1, 2]: return "https://miciicsta01.blob.core.windows.net/miciiccontainer1/"
    if event_driven == 3: return "https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes/"
    if event_driven == 4: return "https://miciicsta01.blob.core.windows.net/miciiccontainer1/uploads/institutes-4/"
    return None

def download_pdf(url: str) -> bytes:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.content
    except Exception as e:
        print_color(f"  Error downloading PDF: {e}", Colors.RED)
    return None

def run_tests(input_file_path: str):
    print_color(f"--- Starting Validation Test Run on '{input_file_path}' ---", Colors.CYAN + Colors.BOLD)
    try:
        df = pd.read_excel(input_file_path) if input_file_path.lower().endswith('.xlsx') else pd.read_csv(input_file_path)
        df.columns = df.columns.str.lower().str.strip()
    except Exception as e:
        print_color(f"Error reading input file: {e}", Colors.RED)
        return

    print("\nInitializing Ollama Client...")
    try:
        ollama_client = OllamaClient()
        if not ollama_client.client: raise ConnectionError("Failed to connect.")
        print_color("Ollama client connected.", Colors.GREEN)
    except Exception as e:
        print_color(f"Error initializing Ollama client: {e}", Colors.RED)
        return

    # Create new columns for results
    results = []
    reasons = []

    for index, row in df.iterrows():
        print(f"\n" + "="*80)
        print_color(f"Running Test Case #{index + 1}/{len(df)}", Colors.BOLD)
        
        # Extract all fields
        activity_name = str(row.get('activity_name', '')).strip()
        theme = str(row.get('event_theme', '')).strip()
        objective = str(row.get('objective', '')).strip()
        benefit_learning = str(row.get('benefit_learning', '')).strip()

        # --- [1] IIC ALIGNMENT VALIDATION ---
        print_color("\n[1] Running IIC Alignment Validation...", Colors.CYAN)
        
        if not activity_name:
            print_color("  Skipped: Missing 'activity_name'.", Colors.YELLOW)
            results.append("SKIPPED")
            reasons.append("Missing activity_name")
            continue
            
        print(f"  - Activity Name: '{activity_name}'")
        print(f"  - Objective: '{objective[:100]}...'" if len(objective) > 100 else f"  - Objective: '{objective}'")
        print(f"  - Learning: '{benefit_learning[:100]}...'" if len(benefit_learning) > 100 else f"  - Learning: '{benefit_learning}'")
        print(f"  - Theme: '{theme}'")
        
        # Use new check_iic_alignment - NOTE: Theme intentionally NOT passed to prevent bias
        passed, reason = ollama_client.check_iic_alignment(
            title=activity_name,
            objectives=objective,
            learning_outcomes=benefit_learning
            # theme intentionally removed to prevent LLM bias
        )
        
        result = "VERIFIED" if passed else "DISAPPROVED"
        results.append(result)
        reasons.append(reason)
        
        print_color(f"  Result: {result} {'✔️' if passed else '❌'}", Colors.GREEN if passed else Colors.RED)
        print(f"  Reason: {reason}")

    # Add results to dataframe
    df['iic_result'] = results
    df['iic_reason'] = reasons

    # Generate output filename
    input_path = Path(input_file_path)
    output_filename = f"{input_path.stem}_output{input_path.suffix}"
    output_path = input_path.parent / output_filename

    # Save output file
    try:
        if output_path.suffix.lower() == '.xlsx':
            df.to_excel(output_path, index=False)
        else:
            df.to_csv(output_path, index=False)
        print("\n" + "="*80)
        print_color(f"--- Results saved to: {output_path} ---", Colors.GREEN + Colors.BOLD)
    except Exception as e:
        print_color(f"Error saving output file: {e}", Colors.RED)

    print("\n" + "="*80)
    print_color("--- Test Run Finished ---", Colors.CYAN + Colors.BOLD)
    
    # Print summary
    verified = results.count("VERIFIED")
    disapproved = results.count("DISAPPROVED")
    skipped = results.count("SKIPPED")
    print(f"\nSummary: {verified} VERIFIED | {disapproved} DISAPPROVED | {skipped} SKIPPED")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run isolated validation tests for the Ollama module.")
    parser.add_argument("input_file", type=str, help="Path to the input CSV or Excel file.")
    args = parser.parse_args()
    run_tests(args.input_file)

