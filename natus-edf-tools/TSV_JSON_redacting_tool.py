## TSV_JSON_redacting_tool (Optimized)
# Author: Dr. Milad Khaki
# Date: 2025-02-21
# Description: This script redacts names from TSV and JSON files based on an Excel list.
# Usage: python TSV_JSON_redacting_tool.py <excel_path> <folder_path>
# License: MIT License

import os
import json
import pandas as pd
import shutil
import csv
# import argparse
import re
import time
# from functools import lru_cache

# Extended regex pattern to allow separators like _ , . | -
SEPARATORS = r"[ _\.,\|;\-]+"

def load_names_from_excel(excel_path):
    """Load last and first names, and their variations from an Excel file."""
    df = pd.read_excel(excel_path, usecols=["LastName", "FirstName"], dtype=str)
    df = df.dropna(subset=["LastName", "FirstName"])  # Ensure no NaN values

    last_names = set(df["LastName"].str.strip().tolist())
    first_names = set(df["FirstName"].str.strip().tolist())

    # Generate name variations
    full_names = set()
    reverse_full_names = set()
    
    for _, row in df.iterrows():
        first = row.FirstName.strip()
        last = row.LastName.strip()
        full_names.add(f"{first} {last}")  # Standard
        reverse_full_names.add(f"{last} {first}")  # Last First

        # Variants with common delimiters
        for sep in ["_", ",", ".", "|", ";", "-", "  "]:  # Double space for handling multiple spaces
            full_names.add(f"{first}{sep}{last}")
            reverse_full_names.add(f"{last}{sep}{first}")

    return last_names, first_names, full_names, reverse_full_names

def prompt_user_for_replacement(line, name):
    """Prompt user to confirm name replacement."""
    print(f"\nFound match: {line.strip()}", flush=True)
    response = input(f"Replace '{name}' with 'X'? (y or enter/n): ").strip().lower()
    return True # response in ["y", ""]

# Cache the compiled regex patterns to avoid recompilation
# @lru_cache(maxsize=1024)
def get_compiled_pattern(name):
    """Get a compiled regex pattern for a name."""
    return re.compile(rf"\b{re.escape(name)}\b|{re.escape(name).replace(' ', SEPARATORS)}", re.IGNORECASE)

def replace_with_case_preserved(text, name):
    """Replace whole word occurrences of `name` with 'X' while preserving the case of the matched text."""
    def replacement(match):
        return "X" if match.group(0)[0].isupper() else "x"
    
    pattern = get_compiled_pattern(name)
    return pattern.sub(replacement, text)

def check_for_name_match(text, name):
    """Check if a name matches in the text."""
    pattern = get_compiled_pattern(name)
    return pattern.search(text) is not None

def process_tsv(file_path, last_names, first_names, full_names, reverse_full_names):
    """Read and redact names in a TSV file."""
    # Cache the entire file in memory
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()
        
    # Parse the cached content
    rows = []
    for line in file_content.splitlines():
        if line.strip():  # Skip empty lines
            rows.append(line.split('\t'))
    
    # Process the cached content
    modified_rows = []
    changed = False
    
    for row in rows:
        new_row = []
        for item in row:
            original_item = item
            for name_set in [last_names, first_names, full_names, reverse_full_names]:
                for name in name_set:
                    if check_for_name_match(item, name):
                        if prompt_user_for_replacement(item, name):
                            item = replace_with_case_preserved(item, name)
                            changed = True
            new_row.append(item)
        modified_rows.append(new_row)
    
    if changed:
        backup_path = file_path + ".bak"
        shutil.copy(file_path, backup_path)
        
        # Write modified content back to file
        with open(file_path, "w", encoding="utf-8", newline='') as f:
            writer = csv.writer(f, delimiter='\t')
            writer.writerows(modified_rows)
        
        print(f" - Modified and backed up to {backup_path}", flush=True)
    else:
        print(" - No changes needed", flush=True)
    
    return changed

def process_json(file_path, last_names, first_names, full_names, reverse_full_names):
    """Read and redact names in a JSON file."""
    # Cache the entire file in memory
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()
    
    # Parse the cached content
    try:
        data = json.loads(file_content)
    except json.JSONDecodeError:
        print(" - Error: Invalid JSON file", flush=True)
        return False
    
    def redact(obj):
        changed = False
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                new_v, v_changed = redact(v)
                result[k] = new_v
                changed = changed or v_changed
            return result, changed
        elif isinstance(obj, list):
            result = []
            for v in obj:
                new_v, v_changed = redact(v)
                result.append(new_v)
                changed = changed or v_changed
            return result, changed
        elif isinstance(obj, str):
            original_obj = obj
            for name_set in [last_names, first_names, full_names, reverse_full_names]:
                for name in name_set:
                    if check_for_name_match(obj, name):
                        if prompt_user_for_replacement(obj, name):
                            obj = replace_with_case_preserved(obj, name)
                            changed = True
            return obj, changed or (obj != original_obj)
        return obj, changed
    
    modified_data, changed = redact(data)
    
    if changed:
        backup_path = file_path + ".bak"
        shutil.copy(file_path, backup_path)
        
        # Write modified content back to file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(modified_data, f, indent=4, ensure_ascii=False)
        
        print(f" - Modified and backed up to {backup_path}", flush=True)
    else:
        print(" - No changes needed", flush=True)
    
    return changed

def search_and_process_files(directory, last_names, first_names, full_names, reverse_full_names):
    """Recursively search for TSV and JSON files and process them."""
    # File types to process - can be easily extended
    file_extensions = {
        ".tsv": process_tsv,
        ".json": process_json
    }
    
    # File collection with file sizes for information
    file_info = []
    total_size = 0
    
    # First, collect all files with their sizes
    print("Scanning for files...", flush=True)
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()
            
            if ext in file_extensions:
                file_size = os.path.getsize(file_path)
                total_size += file_size
                file_info.append({
                    'path': file_path,
                    'type': ext,
                    'size': file_size,
                    'rel_path': os.path.relpath(file_path, directory)
                })
    
    total_files = len(file_info)
    
    # Process all files
    total_changed = 0
    if total_files > 0:
        # Print summary by file type
        type_counts = {}
        for info in file_info:
            type_counts[info['type']] = type_counts.get(info['type'], 0) + 1
        
        summary = ", ".join([f"{count} {ext[1:].upper()} files" for ext, count in type_counts.items()])
        print(f"\nFound {total_files} files to process ({summary})")
        print(f"Total size: {total_size / 1024:.1f} KB", flush=True)
        
        # Sort files by size (smallest first) for faster initial feedback
        file_info.sort(key=lambda x: x['size'])
        
        for idx, info in enumerate(file_info, 1):
            # Progress indicator with percentage
            progress = (idx / total_files) * 100
            print(f"[{idx}/{total_files}] ({progress:.1f}%) Processing {info['type'][1:].upper()} file: {info['rel_path']} ({info['size'] / 1024:.1f} KB)", end="", flush=True)
            
            # Process the file using the appropriate function
            process_func = file_extensions[info['type']]
            changed = process_func(info['path'], last_names, first_names, full_names, reverse_full_names)
                
            if changed:
                total_changed += 1
    else:
        print(f"No files found with extensions: {', '.join(file_extensions.keys())}", flush=True)
    
    return total_changed
            
def main():
    # """Main function to parse arguments and execute the script."""
    # parser = argparse.ArgumentParser(description="Redact names from TSV and JSON files based on an Excel list.")
    # parser.add_argument("excel_path", help="Path to the Excel file containing 'LastName' and 'FirstName' columns.")
    # parser.add_argument("folder_path", help="Folder to scan for TSV and JSON files.")
    # args = parser.parse_args()
    
    # if not os.path.exists(args.excel_path):
    #     print("Error: Excel file not found.")
    #     return
    # if not os.path.exists(args.folder_path):
    #     print("Error: Folder not found.")
    #     return
    
    start_time = time.time()
    class args:
        excel_path = ""
        
    args.excel_path = "e:/iEEG_Demographics.xlsx"
    args.folder_path = "c:/tmp/all_tsv/"
    
    print(f"Loading names from {args.excel_path}...", flush=True)
    last_names, first_names, full_names, reverse_full_names = load_names_from_excel(args.excel_path)
    name_load_time = time.time() - start_time
    
    print(f"Loaded {len(last_names)} last names, {len(first_names)} first names in {name_load_time:.2f} seconds.", flush=True)
    print(f"Scanning directory: {args.folder_path}", flush=True)
    
    process_start_time = time.time()
    total_changed = search_and_process_files(args.folder_path, last_names, first_names, full_names, reverse_full_names)
    process_time = time.time() - process_start_time
    total_time = time.time() - start_time
    
    print("\nProcessing complete.", flush=True)
    print(f"Files modified: {total_changed}", flush=True)
    if total_changed > 0:
        print(f"Backup files created: {total_changed} (.bak extension)", flush=True)
    
    print(f"\nPerformance summary:", flush=True)
    print(f"- Name loading time: {name_load_time:.2f} seconds", flush=True)
    print(f"- Processing time: {process_time:.2f} seconds", flush=True)
    print(f"- Total execution time: {total_time:.2f} seconds", flush=True)

if __name__ == "__main__":
    main()