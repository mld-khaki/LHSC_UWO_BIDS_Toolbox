#!/usr/bin/env python3
"""
EDF Anonymization Scanner

This script recursively scans a directory for EDF files and checks if they are properly
anonymized. It generates a CSV report of any files that are not anonymized and logs
all scanning activity in detail.
"""

import os
import sys
import csv
import logging
import argparse
import traceback
import time
from datetime import datetime
import re
from concurrent.futures import ProcessPoolExecutor
import mmap
from tqdm import tqdm

# Set up logging
def setup_logging(log_dir="logs"):
    """Set up detailed logging to both console and file"""
    # Create logs directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Generate a timestamp for the log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"edf_scanner_{timestamp}.log")
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # File handler with more detailed formatting
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Console handler with less verbose output for better readability
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Log the startup message
    logger.info(f"Logging initialized. Log file: {log_file}")
    return logger, log_file

def is_edf_file(filename):
    """Check if a file is an EDF file based on extension."""
    return filename.lower().endswith(('.edf', '.edf+'))

def check_anonymization(file_path):
    """
    Check if an EDF file is properly anonymized.
    
    Args:
        file_path: Path to the EDF file
        
    Returns:
        dict: Results containing:
            - anonymized: bool - whether the file is anonymized
            - reason: str - reason why the file is considered not anonymized
            - patient_info: str - anonymized patient info field
            - file_size: int - size of the file in bytes
            - error: str - any error message if the check failed
    """
    logger = logging.getLogger('edf_scanner')
    
    result = {
        'anonymized': False,
        'reason': None,
        'patient_info': None,
        'file_size': os.path.getsize(file_path),
        'error': None
    }
    
    try:
        # Open the file and read the header
        with open(file_path, 'rb') as f:
            # Use memory mapping for faster access to large files
            try:
                mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                # Read the header (first 256 bytes)
                header = mmapped_file[:256]
                mmapped_file.close()
            except Exception as e:
                # Fallback if mmap fails (e.g., on very small files)
                logger.debug(f"Memory mapping failed for {file_path}, using direct read: {str(e)}")
                f.seek(0)
                header = f.read(256)
        
        # Extract patient information field (bytes 8-88)
        patient_info = header[8:88].decode('ascii', errors='ignore').strip()
        result['patient_info'] = patient_info
        
        # Check if the patient field is anonymized
        # Patterns to consider as not anonymized:
        patterns = [
            # Real names (sequence of alphabetic words)
            re.compile(r'[A-Za-z]+\s+[A-Za-z]+'),
            # Patient IDs (alphanumeric sequences of 6+ chars)
            re.compile(r'[A-Z0-9]{6,}'),
            # Dates that might be birth dates (various formats)
            re.compile(r'\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}'),
            re.compile(r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}')
        ]
        
        # Check against empty or standard anonymized patterns
        if not patient_info or patient_info in ['X', 'X X X X', 'Anonymized', 'XXXX']:
            result['anonymized'] = True
        else:
            # Check against suspicious patterns
            for pattern in patterns:
                match = pattern.search(patient_info)
                if match:
                    result['anonymized'] = False
                    result['reason'] = f"Patient field contains possible identifiable info: '{match.group()}'"
                    break
            else:
                # If no suspicious patterns found, check if it's only X's or spaces
                if re.match(r'^[X\s]+$', patient_info):
                    result['anonymized'] = True
                else:
                    result['anonymized'] = False
                    result['reason'] = f"Patient field contains non-standard content: '{patient_info}'"
        
        logger.debug(f"File: {file_path}, Anonymized: {result['anonymized']}, Patient info: '{patient_info}'")
        
    except Exception as e:
        error_msg = f"Error checking {file_path}: {str(e)}"
        logger.error(error_msg)
        logger.debug(traceback.format_exc())
        result['error'] = error_msg
    
    return result

def scan_directory(directory, output_csv, max_workers=4):
    """
    Recursively scan a directory for EDF files and check if they are anonymized.
    
    Args:
        directory: Path to the directory to scan
        output_csv: Path to save the CSV report
        max_workers: Maximum number of parallel processes
    """
    logger = logging.getLogger('edf_scanner')
    logger.info(f"Starting scan of directory: {directory}")
    
    # Find all EDF files in the directory and subdirectories
    edf_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if is_edf_file(file):
                edf_files.append(os.path.join(root, file))
    
    logger.info(f"Found {len(edf_files)} EDF files to process")
    
    # Results storage
    all_results = []
    non_anonymized_count = 0
    error_count = 0
    
    # Use process pool for parallel processing
    start_time = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Process files in parallel with progress bar
        with tqdm(total=len(edf_files), desc="Processing EDF files") as pbar:
            futures = [executor.submit(check_anonymization, file_path) for file_path in edf_files]
            
            for i, future in enumerate(futures):
                try:
                    result = future.result()
                    file_path = edf_files[i]
                    
                    # Store the result with the file path
                    result['file_path'] = file_path
                    
                    # Count non-anonymized files
                    if not result['anonymized'] and not result['error']:
                        non_anonymized_count += 1
                        logger.warning(f"Non-anonymized file: {file_path} - {result['reason']}")
                    
                    # Count errors
                    if result['error']:
                        error_count += 1
                    
                    all_results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error processing file {edf_files[i]}: {str(e)}")
                    logger.debug(traceback.format_exc())
                    error_count += 1
                
                pbar.update(1)
    
    elapsed_time = time.time() - start_time
    logger.info(f"Scanning completed in {elapsed_time:.2f} seconds")
    
    # Write non-anonymized files to CSV
    with open(output_csv, 'w', newline='') as csvfile:
        # Define CSV fields
        fieldnames = ['file_path', 'anonymized', 'reason', 'patient_info', 'file_size', 'error']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        # Write only non-anonymized files to CSV
        non_anonymized_written = 0
        for result in all_results:
            if not result['anonymized'] or result['error']:
                writer.writerow(result)
                non_anonymized_written += 1
    
    logger.info(f"Scan results: {len(edf_files)} files processed")
    logger.info(f"- {len(edf_files) - non_anonymized_count - error_count} anonymized")
    logger.info(f"- {non_anonymized_count} non-anonymized")
    logger.info(f"- {error_count} errors")
    logger.info(f"Report of {non_anonymized_written} non-anonymized files saved to: {output_csv}")
    
    return all_results

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Recursively scan directories for EDF files and check if they are anonymized."
    )
    parser.add_argument(
        "directory", 
        help="Directory to scan recursively for EDF files"
    )
    parser.add_argument(
        "--output", 
        default="non_anonymized_edf_files.csv",
        help="Path to save the CSV report (default: non_anonymized_edf_files.csv)"
    )
    parser.add_argument(
        "--log_dir", 
        default="logs",
        help="Directory to store log files (default: logs)"
    )
    parser.add_argument(
        "--log_level", 
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], 
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    parser.add_argument(
        "--max_workers", 
        type=int, 
        default=4,
        help="Maximum number of parallel processes (default: 4)"
    )
    return parser.parse_args()

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()
    
    # Setup logging
    logger, log_file = setup_logging(args.log_dir)
    
    # Set log level
    log_level = getattr(logging, args.log_level)
    logger.setLevel(log_level)
    
    logger.info("=== EDF Anonymization Scanner ===")
    logger.info(f"Scan directory: {args.directory}")
    logger.info(f"Output CSV: {args.output}")
    logger.info(f"Max workers: {args.max_workers}")
    
    # Check if the directory exists
    if not os.path.exists(args.directory):
        logger.error(f"Directory not found: {args.directory}")
        return 1
    
    try:
        # Scan the directory
        scan_directory(args.directory, args.output, args.max_workers)
        logger.info("Scan completed successfully")
        print(f"Scan completed successfully. See {log_file} for details.")
        return 0
    
    except Exception as e:
        logger.error(f"Error during scanning: {str(e)}")
        logger.error(traceback.format_exc())
        print(f"Error during scanning: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
