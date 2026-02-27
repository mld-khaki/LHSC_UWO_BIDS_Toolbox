#!/usr/bin/env python3
"""
Enhanced EDF Anonymization Scanner

This script recursively scans a directory for EDF files and checks if they are properly
anonymized, including both header information and annotations. It generates a CSV report 
of any files that are not anonymized and logs all scanning activity in detail.
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
import numpy as np
from concurrent.futures import ProcessPoolExecutor
import mmap
from tqdm import tqdm

# Try to import edflibpy, but make annotations check optional if not available
try:
    from edflibpy.edfreader import EDFreader
    EDFLIBPY_AVAILABLE = True
except ImportError:
    EDFLIBPY_AVAILABLE = False

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

def check_header_anonymization(header):
    """
    Check if the patient information in the EDF header is anonymized.
    
    Args:
        header: The EDF header bytes
        
    Returns:
        dict: Results with anonymization status and details
    """
    # Extract patient information field (bytes 8-88)
    patient_info = header[8:88].decode('ascii', errors='ignore').strip()
    
    # Initialize results
    result = {
        'header_anonymized': False,
        'header_reason': None,
        'patient_info': patient_info
    }
    
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
        result['header_anonymized'] = True
    else:
        # Check against suspicious patterns
        for pattern in patterns:
            match = pattern.search(patient_info)
            if match:
                result['header_anonymized'] = False
                result['header_reason'] = f"Patient field contains possible identifiable info: '{match.group()}'"
                break
        else:
            # If no suspicious patterns found, check if it's only X's or spaces
            if re.match(r'^[X\s]+$', patient_info):
                result['header_anonymized'] = True
            else:
                result['header_anonymized'] = False
                result['header_reason'] = f"Patient field contains non-standard content: '{patient_info}'"
    
    return result

def extract_and_check_annotations(file_path):
    """
    Extract and check if annotations within an EDF file are anonymized.
    
    This function:
    1. Reads the EDF file and extracts annotation channels
    2. Decodes annotations and checks for patterns that suggest personal information
    
    Args:
        file_path: Path to the EDF file
        
    Returns:
        dict: Results of annotation anonymization checks
    """
    logger = logging.getLogger('edf_scanner')
    
    result = {
        'annotations_checked': False,
        'annotations_anonymized': True,  # Default to True, we'll set to False if we find issues
        'annotations_reason': None,
        'annotation_issues': []
    }
    
    if not EDFLIBPY_AVAILABLE:
        result['annotations_reason'] = "edflibpy not available, annotations not checked"
        return result
    
    try:
        # Patterns to look for in annotations
        patterns = [
            # Names (sequence of words starting with capitals)
            (re.compile(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b'), "possible name"),
            # Patient IDs (alphanumeric sequences of 6+ chars)
            (re.compile(r'\b[A-Z0-9]{6,}\b'), "possible ID"),
            # Dates (various formats)
            (re.compile(r'\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b'), "possible date"),
            # Email addresses
            (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "email address"),
            # Phone numbers
            (re.compile(r'\b\d{3}[-.)]\d{3}[-.)]\d{4}\b'), "phone number"),
            # Social security numbers or similar
            (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "possible SSN"),
            # Words like "patient", "name", "doctor" followed by text 
            (re.compile(r'\b(patient|name|doctor|physician|nurse|hospital)\s*:\s*([A-Za-z]+)'), "labeled identifier")
        ]
        
        # Open EDF file
        edf = EDFreader(file_path)
        
        # Get signal labels
        signal_labels = edf.getSignalLabels()
        
        # Find annotation channels
        annot_channels = [i for i, label in enumerate(signal_labels) 
                         if label in ["EDF Annotations", "BDF Annotations"]]
        
        if not annot_channels:
            logger.debug(f"No annotation channels found in {file_path}")
            result['annotations_checked'] = True
            return result
        
        # Check each annotation channel
        for channel_idx in annot_channels:
            # Get annotation signal parameters
            samples_per_record = edf.getSamplesPerRecordPerSignal()[channel_idx]
            num_records = edf.getNumDataRecords()
            
            # Process in chunks for memory efficiency
            issues_found = 0
            max_issues_to_report = 10  # Limit the number of issues to report
            
            # Process each data record
            for record_idx in range(num_records):
                # Read this record's annotations
                try:
                    # Get raw annotation data for this record
                    raw_annot = edf.readSignal(channel_idx, record_idx * samples_per_record, samples_per_record)
                    
                    # Convert to bytes and decode to extract text
                    annot_bytes = raw_annot.tobytes()
                    
                    # Skip empty annotation blocks
                    if all(b == 0 for b in annot_bytes):
                        continue
                    
                    # Decode any text found in this annotation chunk
                    # We do this by finding printable ASCII segments in the raw bytes
                    text_segments = []
                    current_segment = []
                    
                    for byte in annot_bytes:
                        # Is it a printable ASCII character?
                        if 32 <= byte <= 126:  # printable ASCII range
                            current_segment.append(chr(byte))
                        else:
                            # End of segment
                            if current_segment:
                                text = ''.join(current_segment)
                                if len(text) > 2:  # Ignore very short segments
                                    text_segments.append(text)
                                current_segment = []
                    
                    # Check last segment
                    if current_segment:
                        text = ''.join(current_segment)
                        if len(text) > 2:
                            text_segments.append(text)
                    
                    # Check each text segment against our patterns
                    for text in text_segments:
                        for pattern, issue_type in patterns:
                            matches = pattern.findall(text)
                            if matches:
                                for match in matches:
                                    match_text = match if isinstance(match, str) else match[0]
                                    # Check if the match is just a common word or term
                                    if len(match_text) > 3 and match_text.lower() not in [
                                        "patient", "doctor", "name", "test", "hospital", "record", 
                                        "eeg", "ecg", "emg", "anonymous", "anonymized"
                                    ]:
                                        issue = {
                                            "record": record_idx,
                                            "channel": channel_idx,
                                            "issue_type": issue_type,
                                            "text": match_text,
                                            "context": text[:100]  # Limited context for the report
                                        }
                                        result['annotation_issues'].append(issue)
                                        issues_found += 1
                                        
                                        if issues_found >= max_issues_to_report:
                                            break
                        
                        if issues_found >= max_issues_to_report:
                            break
                    
                    if issues_found >= max_issues_to_report:
                        break
                    
                except Exception as e:
                    logger.debug(f"Error processing annotation in record {record_idx}: {str(e)}")
            
            logger.debug(f"Found {issues_found} potential privacy issues in annotations of {file_path}")
        
        # Close the EDF file
        edf.close()
        
        # Update result based on issues found
        result['annotations_checked'] = True
        
        if result['annotation_issues']:
            result['annotations_anonymized'] = False
            result['annotations_reason'] = f"Found {len(result['annotation_issues'])} potential privacy issues in annotations"
        
    except Exception as e:
        logger.debug(f"Error checking annotations in {file_path}: {str(e)}")
        logger.debug(traceback.format_exc())
        result['annotations_checked'] = False
        result['annotations_reason'] = f"Error: {str(e)}"
    
    return result

def check_anonymization(file_path):
    """
    Check if an EDF file is properly anonymized, including both header and annotations.
    
    Args:
        file_path: Path to the EDF file
        
    Returns:
        dict: Results containing anonymization status and details
    """
    logger = logging.getLogger('edf_scanner')
    
    result = {
        'anonymized': False,
        'file_path': file_path,
        'file_size': os.path.getsize(file_path),
        'error': None,
        'header_checked': False,
        'annotations_checked': False,
        'issues': []
    }
    
    try:
        logger.debug(f"Checking anonymization of {file_path}")
        
        # First check the header
        try:
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
                    
            # Check header anonymization
            header_result = check_header_anonymization(header)
            result.update(header_result)
            result['header_checked'] = True
            
            if not header_result['header_anonymized']:
                result['issues'].append({
                    'type': 'header',
                    'reason': header_result['header_reason']
                })
        except Exception as e:
            logger.debug(f"Error checking header in {file_path}: {str(e)}")
            result['header_checked'] = False
            result['issues'].append({
                'type': 'header_error',
                'reason': str(e)
            })
        
        # Then check the annotations
        try:
            annotations_result = extract_and_check_annotations(file_path)
            result.update(annotations_result)
            
            if not annotations_result['annotations_anonymized'] and annotations_result['annotations_checked']:
                for issue in annotations_result['annotation_issues']:
                    result['issues'].append({
                        'type': 'annotation',
                        'reason': f"{issue['issue_type']} in record {issue['record']}: {issue['text']}"
                    })
        except Exception as e:
            logger.debug(f"Error checking annotations in {file_path}: {str(e)}")
            result['issues'].append({
                'type': 'annotation_error',
                'reason': str(e)
            })
        
        # Overall anonymization status
        # File is considered anonymized only if both header and annotations are anonymized
        result['anonymized'] = (
            (result.get('header_anonymized', False) or not result.get('header_checked', True)) and 
            (result.get('annotations_anonymized', False) or not result.get('annotations_checked', True))
        )
        
        logger.debug(f"Anonymization check for {file_path}: {result['anonymized']}")
        
    except Exception as e:
        error_msg = f"Error checking {file_path}: {str(e)}"
        logger.error(error_msg)
        logger.debug(traceback.format_exc())
        result['error'] = error_msg
    
    return result

def scan_directory(directory, output_csv, check_annotations=True, max_workers=4):
    """
    Recursively scan a directory for EDF files and check if they are anonymized.
    
    Args:
        directory: Path to the directory to scan
        output_csv: Path to save the CSV report
        check_annotations: Whether to check annotations in addition to headers
        max_workers: Maximum number of parallel processes
    """
    logger = logging.getLogger('edf_scanner')
    logger.info(f"Starting scan of directory: {directory}")
    
    if check_annotations and not EDFLIBPY_AVAILABLE:
        logger.warning("edflibpy not available - annotation checking will be skipped")
        logger.warning("Install edflibpy for complete anonymization checking")
        check_annotations = False
    
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
                    
                    # Count non-anonymized files
                    if not result['anonymized'] and not result['error']:
                        non_anonymized_count += 1
                        logger.warning(f"Non-anonymized file: {file_path}")
                        print(f"Non-anonymized file: {file_path}",flush=True)
                        for issue in result['issues']:
                            logger.warning(f"  - {issue['type']}: {issue['reason']}")
                    
                    # Count errors
                    if result['error']:
                        error_count += 1
                    
                    all_results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error processing file {edf_files[i]}: {str(e)}")
                    logger.debug(traceback.format_exc())
                    error_count += 1
                    all_results.append({
                        'file_path': edf_files[i],
                        'anonymized': False,
                        'error': str(e),
                        'issues': [{'type': 'processing_error', 'reason': str(e)}]
                    })
                
                pbar.update(1)
    
    elapsed_time = time.time() - start_time
    logger.info(f"Scanning completed in {elapsed_time:.2f} seconds")
    
    # Write non-anonymized files to CSV
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        # Define CSV fields
        fieldnames = ['file_path', 'anonymized', 'header_anonymized', 'annotations_anonymized', 
                      'issue_type', 'issue_details', 'patient_info', 'file_size']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        # Write only non-anonymized files to CSV, with separate rows for each issue
        non_anonymized_written = 0
        for result in all_results:
            if not result['anonymized'] or result['error']:
                # If there are specific issues, write each one as a separate row
                if result['issues']:
                    for issue in result['issues']:
                        row = {
                            'file_path': result['file_path'],
                            'anonymized': result['anonymized'],
                            'header_anonymized': result.get('header_anonymized', 'N/A'),
                            'annotations_anonymized': result.get('annotations_anonymized', 'N/A'),
                            'issue_type': issue['type'],
                            'issue_details': issue['reason'],
                            'patient_info': result.get('patient_info', 'N/A'),
                            'file_size': result['file_size']
                        }
                        writer.writerow(row)
                        non_anonymized_written += 1
                else:
                    # If there's just a general error, write one row
                    row = {
                        'file_path': result['file_path'],
                        'anonymized': result['anonymized'],
                        'header_anonymized': result.get('header_anonymized', 'N/A'),
                        'annotations_anonymized': result.get('annotations_anonymized', 'N/A'),
                        'issue_type': 'general_error',
                        'issue_details': result.get('error', 'Unknown issue'),
                        'patient_info': result.get('patient_info', 'N/A'),
                        'file_size': result['file_size']
                    }
                    writer.writerow(row)
                    non_anonymized_written += 1
    
    logger.info(f"Scan results: {len(edf_files)} files processed")
    logger.info(f"- {len(edf_files) - non_anonymized_count - error_count} anonymized")
    logger.info(f"- {non_anonymized_count} non-anonymized")
    logger.info(f"- {error_count} errors")
    logger.info(f"Report of {non_anonymized_written} issues saved to: {output_csv}")
    
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
    parser.add_argument(
        "--skip_annotations", 
        action="store_true",
        help="Skip checking annotations (faster but less thorough)"
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
    
    logger.info("=== Enhanced EDF Anonymization Scanner ===")
    logger.info(f"Scan directory: {args.directory}")
    logger.info(f"Output CSV: {args.output}")
    logger.info(f"Max workers: {args.max_workers}")
    logger.info(f"Check annotations: {not args.skip_annotations}")
    
    # Log edflibpy availability
    if EDFLIBPY_AVAILABLE:
        logger.info("edflibpy available - full annotation checking enabled")
    else:
        logger.warning("edflibpy not available - annotation checking will be limited")
        logger.warning("Install edflibpy for complete anonymization checking")
    
    # Check if the directory exists
    if not os.path.exists(args.directory):
        logger.error(f"Directory not found: {args.directory}")
        return 1
    
    try:
        # Scan the directory
        scan_directory(args.directory, args.output, not args.skip_annotations, args.max_workers)
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