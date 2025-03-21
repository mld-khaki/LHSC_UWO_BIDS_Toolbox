## Natus metadata extraction tool
# Author: Dr. Milad Khaki
# Date: 2025-02-21
# Description: Extracts metadata from Natus EEG files, including nested key-value structures and folder statistics.
# Usage: python Natus_InfoServerScraper.py <input_dir> [-o output.xlsx] [-p pattern]
# License: MIT License

import os
import re
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

EXCEL_EPOCH = datetime(1899, 12, 30)  # Base date for Excel/Natus timestamps

def convert_excel_date(excel_time):
    """Convert Excel-style floating point date to YYYY-MM-DD HH:MM:SS format safely."""
    try:
        excel_time = float(excel_time)  # Ensure it's a float
        
        # Ensure the timestamp is within a reasonable range (Natus timestamps should be within 1800-2100)
        if excel_time < 0 or excel_time > 80000:  # Approx 2199-12-31 in Excel format
            return str(excel_time)  # Return as string if out of range

        converted_time = EXCEL_EPOCH + timedelta(days=excel_time)
        return converted_time.strftime("%Y-%m-%d %H:%M:%S")
    
    except (ValueError, TypeError, OverflowError):
        return str(excel_time)  # Return as string if conversion fails

def get_folder_stats(folder_path):
    """Calculate folder size, number of files, and number of EEG files."""
    folder = Path(folder_path)
    total_size = sum(f.stat().st_size for f in folder.glob("**/*") if f.is_file())  # Total size in bytes
    num_files = sum(1 for f in folder.glob("**/*") if f.is_file())  # Total number of files
    num_eeg_files = sum(1 for f in folder.glob("**/*.eeg"))  # Number of .eeg files

    return total_size, num_files, num_eeg_files

def parse_metadata(content, parent_key=""):
    """Extracts key-value pairs recursively from structured data."""
    metadata = {}
    
    # Match keys dynamically, allowing for nested structures
    pattern = r'\(\."([^"]+)"\s*,\s*(.*?)\)'

    for match in re.finditer(pattern, content):
        key, value = match.groups()
        full_key = f"{parent_key}_{key}" if parent_key else key  # Handle nested keys

        # Skip excessively large values (>1024 characters)
        if len(value) > 1024:
            continue

        # Check if value contains another key-value structure (nested data)
        if re.search(r'\(\."([^"]+)"\s*,', value):
            sub_metadata = parse_metadata(value, full_key)
            metadata.update(sub_metadata)
        else:
        # Convert timestamps stored as floats
            if "timespan" in full_key.lower():    
                pass
            else:
                if "Time" in full_key or "Date" in full_key or "Timestamp" in full_key:
                    value = convert_excel_date(value)

        metadata[full_key] = value.strip()

    return metadata

def extract_eeg_metadata(directory, pattern=None):
    """Extract metadata from all .eeg files in directory, filtered by pattern."""
    all_metadata = []
    
    #if pattern:
     #   pattern_regex = re.compile(pattern)

    # First, find all relevant folders based on the pattern
    all_folders = set()
    filtered_folders = []
    for folder_tmp in os.listdir(directory):
        folder = folder_tmp #os.path.join(directory, folder)
        #print(folder,len(filtered_folders))
        
        #print(pattern)
        if pattern.lower() in folder.lower():
            filtered_folders.append(folder.lower())
            print(f"\nFound {folder}",flush=True,end="")
        else:
            #print(folder.lower())
            if len(folder) > 1:
                name = folder[0:2]
            else:
                name = ".."
            #print(f"{name}",sep="",end="",flush=True)
    print("")
    
    # Filter folders based on pattern if provided
    
    # Process each matching folder
    cnt = 0
    for folder in filtered_folders:
        cnt += 1
        eeg_file = directory + "\\" +    folder + "\\" + folder +".eeg"
        if not os.path.isfile(eeg_file):
            print(f"File not found! {eeg_file}")
        else:
            try:
                # Read file content
                with open(eeg_file, 'rb') as f:
                    content = f.read().decode('utf-8', errors='ignore')

                # Parse metadata recursively
                metadata = parse_metadata(content)

                # Extract essential fields
                study_name = metadata.get("StudyName", "Unknown")
                folder_name = folder
                total_size, num_files, num_eeg_files = get_folder_stats(directory + "\\" + folder)  # Get folder stats

                # Extract all duration fields (e.g., multiple timespans)
                duration_keys = [k for k in metadata if "timespan" in k.lower() or "Duration" in k]
                durations = {f"Duration_{i+1}": metadata[k] for i, k in enumerate(duration_keys)}

                eeg_no = metadata.get("EegNo", "Unknown") 
                machine = metadata.get("Machine", "Unknown")  

                # Extract all timestamps and dates
                date_keys = []
                for k in metadata:
                    kk = k.lower()
                    if ("date" in kk) or ("time" in kk) or ("timestamp" in kk):
                        date_keys.append(k)
                
                print(f"({cnt}/{len(filtered_folders)}) Processing {eeg_file}")
                date_metadata = {k: str(metadata[k]) for k in date_keys}  # Ensure all dates are strings

                # Order DataFrame: StudyName, FolderName, Folder Stats, Durations, then others
                ordered_metadata = {
                    "StudyName": study_name,
                    "FolderName": folder_name,
                    "FolderSize GB": total_size / (1024**3),  # Folder size in GB
                    "NumFiles": num_files,  # Total number of files
                    "NumEEGFiles": num_eeg_files,  # Number of EEG files
                    "EegNo": eeg_no,
                    "Machine": machine
                }
                ordered_metadata.update(durations)  # Include all extracted duration fields
                ordered_metadata.update(date_metadata)  # Insert extracted timestamps next
                ordered_metadata.update(metadata)  # Append remaining metadata

                ordered_metadata["source_file"] = str(eeg_file)  # Track source file
                all_metadata.append(ordered_metadata)

            except Exception as e:
                raise(e)
                print(f"Error processing {eeg_file}: {e}")

    return all_metadata

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract metadata from Natus EEG files")
    parser.add_argument('input_dir', help="Directory containing .eeg files")
    parser.add_argument('-o', '--output', default='eeg_metadata.xlsx', help="Output Excel file")
    parser.add_argument('-p', '--pattern', help="Pattern to match folder names (e.g. 'SUBJECT_' for folders starting with SUBJECT_)")

    args = parser.parse_args()

    print(f"Processing files in {args.input_dir}")
    if args.pattern:
        print(f"Looking for folders matching pattern: {args.pattern}")
    
    metadata_list = extract_eeg_metadata(args.input_dir, args.pattern)

    if metadata_list:
        # Convert to DataFrame
        df = pd.DataFrame(metadata_list)

        # Save to Excel
        print(f"Saving to {args.output}")
        df.to_excel(args.output, index=False)
        print(f"Processed {len(metadata_list)} files from {len(set(item['FolderName'] for item in metadata_list))} folders")
        print("\nExtracted fields (ordered):")
        print("\n".join(df.columns[:20]))  # Show first 20 columns for brevity
        print(f"...and {len(df.columns) - 20} more columns")
    else:
        print("No data found matching the specified criteria")
